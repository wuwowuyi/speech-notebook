#
# From https://cloud.google.com/speech-to-text/docs/streaming-recognize#perform_streaming_speech_recognition_on_an_audio_stream
#
import asyncio
import queue
from datetime import datetime

import pyaudio
from google.cloud import speech

# Audio recording parameters
RATE = 16000  # sampling rate, the number of frames per second
CHUNK = 1024 * 8  # frames per buffer.
CHUNK_DURATION = CHUNK / RATE  # the duration of a chunk

# Google charges each request rounded up to the nearest increment of 15 seconds
# We limit each request no more than but close to 15 seconds
MAX_LENGTH_PER_REQUEST = 15


class MicrophoneStream:
    """Opens a recording stream as a generator yielding the audio chunks."""

    def __init__(self, rate: int, chunk: int):
        self._rate = rate
        self._chunk = chunk
        self._buff = queue.Queue()  # a thread-safe buffer of audio data
        self._closed = True  # stream status flag

    def __enter__(self):
        self._audio_interface = pyaudio.PyAudio()
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self._rate,
            input=True,
            output=False,
            frames_per_buffer=self._chunk,
            # Run the audio stream asynchronously to fill the buffer object.
            # This is necessary so that the input device's buffer doesn't
            # overflow while the calling thread makes network requests, etc.
            stream_callback=self._fill_buffer,
        )
        self._closed = False
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        # TODO: parameters, deal with exceptions
        self._audio_stream.stop_stream()
        self._audio_stream.close()
        self._closed = True
        # Signal the generator to terminate so that the client's
        # streaming_recognize method will not block the process termination.
        self._buff.put(None)
        self._audio_interface.terminate()

    def _fill_buffer(self, in_data, frame_count, time_info, status_flags):
        """Call back function to continuously collect data from the audio stream into the buffer.

        see http://people.csail.mit.edu/hubert/pyaudio/docs/#pyaudio.Stream.__init__
        for the signature of a callback function.
        frame_count equals the buffer size.
        During a normal recording, the observed value of status_flag is paContinue.
        """

        if status_flags in (pyaudio.paInputUnderflow, pyaudio.paInputOverflow):
            raise Exception  # TODO. add log

        duration = time_info.get('current_time', 0) - time_info.get('input_buffer_adc_time', 0)
        if duration <= 0 or duration > CHUNK_DURATION * 3:
            print('error loading time info')  # TODO: log this error
            return None, pyaudio.paContinue  # ignore this data chunk

        self._buff.put((in_data.copy(), duration))
        return None, pyaudio.paContinue

    def generator(self):
        """Called to generate audio data read from buffer. """
        # total length of audio generated in one call to this function.
        length = 0  # in seconds

        data = []
        while not self._closed:
            while True:
                try:
                    item = self._buff.get(block=True, timeout=CHUNK_DURATION * 1.2)
                    if item is None:
                        return
                    chunk, duration = item
                    data.append(chunk)
                    length += duration
                    if MAX_LENGTH_PER_REQUEST - length < (CHUNK_DURATION * 1.2):
                        print(f"yield data and return, the length is {length}")  # TODO, log debug
                        # stop reading data from buffer.
                        yield b"".join(data)
                        return
                except queue.Empty:
                    break

            if len(data) > 0:
                print('Queue is emtpy. yield data block')
                yield b"".join(data)
                data.clear()

    def closed(self):
        return self._closed


def _listen_print_loop(responses):
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


def _transcribe(client: speech.SpeechClient,
                config: speech.StreamingRecognitionConfig,
                requests_queue: queue.Queue):
    while True:
        try:
            requests = requests_queue.get(block=True, timeout=0.05)
            print(f"start streaming recognize at {datetime.utcnow().strftime('%H:%M:%S.%f')}")
            responses = client.streaming_recognize(config, requests)
            requests_queue.task_done()

            # Now, put the transcription responses to use.
            print(f"start printing responses at {datetime.utcnow().strftime('%H:%M:%S.%f')}")
            _listen_print_loop(responses)
        except queue.Empty:
            print('no more requests.')
            return


async def main():
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
        requests_queue = queue.Queue(3)  # TODO: put a limit on queue

        while not stream.closed():
            requests = (
                speech.StreamingRecognizeRequest(audio_content=content)
                for content in stream.generator()
            )

            try:
                requests_queue.put_nowait(requests)
            except queue.Full:
                print("Google cloud API is too slow. aborting.")
                break

            num_threads = requests_queue.qsize()
            asyncio.gather(
                *(asyncio.to_thread(_transcribe, client, streaming_config, requests_queue)
                  for i in num_threads)
            )


if __name__ == "__main__":
    main()
