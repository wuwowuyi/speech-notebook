#
# From https://cloud.google.com/speech-to-text/docs/streaming-recognize#perform_streaming_speech_recognition_on_an_audio_stream
#
import asyncio
import copy
import logging
import queue
from datetime import datetime

import pyaudio
from google.cloud import speech

logger = logging.getLogger("asyncio")  # TODO

# Audio recording parameters
RATE = 16000  # sampling rate, the number of frames per second
CHUNK = 1024  # frames per buffer.
CHUNK_DURATION = CHUNK / RATE  # the duration of a chunk

# Google charges each request rounded up to the nearest increment of 15 seconds
# We limit each request no more than but close to 15 seconds
MAX_LENGTH_PER_REQUEST = 15


class MicrophoneStream:
    """Opens a recording stream as a generator yielding the audio chunks."""

    def __init__(self, rate: int, chunk: int, main_loop):
        self._rate = rate
        self._chunk = chunk
        self._closed = True  # stream status flag
        self._in_buff = asyncio.Queue()  # in audio from microphone
        self._out_buff = queue.Queue()  # out audio to transcribe
        self.main_loop = main_loop  # event loop of the main thread

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
        self._in_buff.put_nowait(None)
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

        self.main_loop.call_soon_threadsafe(self._in_buff.put_nowait, (copy.copy(in_data), duration))
        return None, pyaudio.paContinue

    async def generate(self):
        """Called to generate audio data read from buffer. """
        print(f"Data generation started at {datetime.utcnow().strftime('%H:%M:%S')}")
        length = 0  # in seconds
        data = []
        while True:
            try:
                item = await self._in_buff.get()
                if item is None:
                    break
                chunk, duration = item
                data.append(chunk)
                length += duration
                if MAX_LENGTH_PER_REQUEST - length < CHUNK_DURATION * 1.5:
                    print(f"yield data and return at {datetime.utcnow().strftime('%H:%M:%S')}, the length is {length}")  # TODO, log debug
                    # stop reading data from buffer.
                    self._out_buff.put(copy.copy(b"".join(data)))
                    data.clear()
                    length = 0
            except:
                break

        if len(data) > 0:
            print('Queue is emtpy. yield remaining data block')
            self._out_buff.put(copy.copy(b"".join(data)))
        self._out_buff.put(None)

    def closed(self):
        return self._closed

    def out_queue(self):
        return self._out_buff


def _listen_print_loop(response):
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

    if not response.results:
        return

    # The `results` list is consecutive. For streaming, we only care about
    # the first result being considered, since once it's `is_final`, it
    # moves on to considering the next utterance.
    result = response.results[0]
    if result.alternatives:
        transcript = result.alternatives[0].transcript
        print(transcript)


def _transcribe(config: speech.RecognitionConfig, data_queue):
    #logger.info(f"Transcribe thread started at {time.strfmt('%X')}")
    print(f"Transcribe thread started at {datetime.utcnow().strftime('%H:%M:%S')}")
    with speech.SpeechClient() as client:
        while True:
            try:
                content = data_queue.get(timeout=MAX_LENGTH_PER_REQUEST)  # wait for data. blocking
                if content is None:
                    return

                audio = speech.RecognitionAudio(content=content)
                print(f"start streaming recognize at {datetime.utcnow().strftime('%H:%M:%S.%f')}")
                response = client.recognize(config=config, audio=audio)

                # Now, put the transcription responses to use.
                print(f"start printing responses at {datetime.utcnow().strftime('%H:%M:%S.%f')}")
                _listen_print_loop(response)
            except queue.Empty:
                break


async def main():
    # See http://g.co/cloud/speech/docs/languages
    # for a list of supported languages.
    language_code = "zh"  # a BCP-47 language tag

    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RATE,
        audio_channel_count=1,
        language_code=language_code,
        model='default',
        enable_automatic_punctuation=True,
    )

    event_loop = asyncio.get_running_loop()

    with MicrophoneStream(RATE, CHUNK, event_loop) as stream:
        await asyncio.gather(
            stream.generate(),
            asyncio.to_thread(_transcribe, config, stream.out_queue())
        )


if __name__ == "__main__":
    asyncio.run(main())
