#
# From https://cloud.google.com/speech-to-text/docs/streaming-recognize#perform_streaming_speech_recognition_on_an_audio_stream
#
import threading
import time
from datetime import datetime

from google.cloud import speech

import pyaudio
import queue

# Audio recording parameters
RATE = 16000  # sampling rate, the number of frames per second
# CHUNK = int(RATE / 10)  # 100ms. frames per buffer. I need RATE * 14.5
CHUNK = 1024 * 8
CHUNK_LENGTH = CHUNK / RATE  # the length of recording per chunk

# Google charges each request rounded up to the nearest increment of 15 seconds
# We limit each request no more than but close to 15 seconds
MAX_LENGTH_PER_REQUEST = 15

class MicrophoneStream:
    """Opens a recording stream as a generator yielding the audio chunks."""

    def __init__(self, rate, chunk):
        self._rate = rate
        self._chunk = chunk

        # Create a thread-safe buffer of audio data
        self._buff = queue.Queue()
        self._closed = True

    def __enter__(self):
        self._audio_interface = pyaudio.PyAudio()
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paInt16,
            # The API currently only supports 1-channel (mono) audio
            # https://goo.gl/z757pE
            channels=1,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk,
            # Run the audio stream asynchronously to fill the buffer object.
            # This is necessary so that the input device's buffer doesn't
            # overflow while the calling thread makes network requests, etc.
            stream_callback=self._fill_buffer,
        )

        self._closed = False

        return self

    def __exit__(self, type, value, traceback):
        self._audio_stream.stop_stream()
        self._audio_stream.close()
        self._closed = True
        # Signal the generator to terminate so that the client's
        # streaming_recognize method will not block the process termination.
        self._buff.put(None)
        self._audio_interface.terminate()

    def _fill_buffer(self, in_data, frame_count, time_info, status_flags):
        """Continuously collect data from the audio stream, into the buffer."""
        # frame_count equals buffer size.

        # http://people.csail.mit.edu/hubert/pyaudio/docs/#pyaudio.paContinue
        #print(status_flags)  # output 0

        duration = time_info.get('current_time', 0) - time_info.get('input_buffer_adc_time', 0)
        if duration <= 0:
            print('error loading time info')  # TODO: log this error
            return None, pyaudio.paContinue  # ignore this data chunk
        self._buff.put((in_data, duration))
        return None, pyaudio.paContinue

    def generator(self):
        data = []
        length = 0  # in seconds
        while not self._closed:
            while True:
                try:
                    item = self._buff.get(block=False)
                    if item is None:
                        return
                    chunk, duration = item
                    data.append(chunk)
                    length += duration
                    if MAX_LENGTH_PER_REQUEST - length < (CHUNK_LENGTH * 1.3):
                        print(f"yield data and return, the length is {length}")
                        # stop reading data from buffer.
                        yield b"".join(data)
                        return
                except queue.Empty:
                    break

            if len(data) > 0:
                yield b"".join(data)
                data.clear()

    def closed(self):
        return self._closed


def listen_print_loop(responses):
    """Iterates through server responses and prints them.

    The responses passed is a generator that will block until a response
    is provided by the server.

    Each response may contain multiple results, and each result may contain
    multiple alternatives; for details, see https://goo.gl/tjCPAU.  Here we
    print only the transcription for the top alternative of the top result.

    In this case, responses are provided for interim results as well. If the
    response is an interim one, print a line feed at the end of it, to allow
    the next result to overwrite it, until the response is a final one. For the
    final one, print a newline to preserve the finalized transcription.
    """
    # https://cloud.google.com/python/docs/reference/speech/latest/google.cloud.speech_v1.types.StreamingRecognizeResponse
    for response in responses:
        if not response.results:
            continue

        # The `results` list is consecutive. For streaming, we only care about
        # the first result being considered, since once it's `is_final`, it
        # moves on to considering the next utterance.
        result = response.results[0]
        if not result.alternatives:
            continue

        if result.is_final:
            # Display the transcription of the top alternative.
            transcript = result.alternatives[0].transcript
            print(transcript)
            break


def main():
    # See http://g.co/cloud/speech/docs/languages
    # for a list of supported languages.
    language_code = "zh"  # a BCP-47 language tag

    client = speech.SpeechClient()
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RATE,
        audio_channel_count=1,
        language_code=language_code,
        model='default',
        enable_automatic_punctuation=True,
    )

    streaming_config = speech.StreamingRecognitionConfig(
        config=config,
        single_utterance=False,
        interim_results=False
    )

    with MicrophoneStream(RATE, CHUNK) as stream:
        print(f"start recording at {datetime.utcnow().strftime('%H:%M:%S.%f')}")

        while not stream.closed():
            audio_generator = stream.generator()
            requests = (
                speech.StreamingRecognizeRequest(audio_content=content)
                for content in audio_generator
            )

            #print(f'number of active threads {threading.active_count()}')

            print(f"start streaming recognize at {datetime.utcnow().strftime('%H:%M:%S.%f')}")
            responses = client.streaming_recognize(streaming_config,
                                                   requests)

            # Now, put the transcription responses to use.
            print(f"start printing responses at {datetime.utcnow().strftime('%H:%M:%S.%f')}")
            listen_print_loop(responses)


if __name__ == "__main__":
    main()
