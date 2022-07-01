from __future__ import annotations
from typing import *

import functools
import time

import asyncio
import copy
import logging
import queue
from datetime import datetime

import pyaudio
from PyQt6.QtCore import QObject, pyqtSignal
from google.cloud import speech

# Audio recording parameters
RATE = 16000  # sampling rate, the number of frames per second
CHUNK = 1024  # frames per buffer.
CHUNK_DURATION = CHUNK / RATE  # the duration of a chunk

# Google charges each request rounded up to the nearest increment of 15 seconds
# We limit each request no more than but close to 15 seconds
MAX_LENGTH_PER_REQUEST = 15


class MicrophoneStream:
    """Opens a recording stream as a generator yielding the audio chunks."""

    def __init__(self, rate: int, chunk: int, out_buff: queue.Queue[bytes]):
        self._rate = rate
        self._chunk = chunk
        self._closed = True  # stream status flag
        self._in_buff: asyncio.Queue[bytes] = asyncio.Queue()  # in audio from microphone
        self._out_buff = out_buff  # out audio to transcribe

    def __enter__(self):
        loop = asyncio.get_running_loop()
        self._audio_interface = pyaudio.PyAudio()
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self._rate,
            input=True,
            output=False,
            frames_per_buffer=self._chunk,
            stream_callback=functools.partial(self._fill_buffer, loop),
        )
        self._closed = False
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        # TODO: parameters, deal with exceptions
        self._audio_stream.stop_stream()
        self._audio_stream.close()
        self._audio_interface.terminate()
        self._closed = True

    def stop(self):
        logging.debug('stopping microphone...')
        self._in_buff.put_nowait(None)

    def _fill_buffer(self, loop, in_data: bytes, frame_count: int, time_info: Mapping[str, float],
                     status_flags: int) -> (
            None, int):
        """Call back function to continuously collect data from the audio stream into the buffer.
        This will be called from the Microphone recording thread.

        see http://people.csail.mit.edu/hubert/pyaudio/docs/#pyaudio.Stream.__init__
        for the signature of a callback function.
        frame_count equals the buffer size.
        During a normal recording, the observed value of status_flag is paContinue.
        """

        if status_flags in (pyaudio.paInputUnderflow, pyaudio.paInputOverflow):
            logging.warning(f"error in filling buffers. status is {status_flags}")
            raise Exception

        duration = time_info.get('current_time', 0) - time_info.get('input_buffer_adc_time', 0)
        if duration <= 0 or duration > CHUNK_DURATION * 3:
            logging.error('error loading time info')
            return None, pyaudio.paContinue  # ignore this data chunk

        loop.call_soon_threadsafe(self._in_buff.put_nowait, (copy.copy(in_data), duration))
        return None, pyaudio.paContinue

    async def generate(self):
        """Called to read audio data from microphone into output buffer. """
        logging.debug(f"\nData generation started at {datetime.now().strftime('%H:%M:%S')}")
        length = 0  # in seconds
        data = b""
        try:
            while True:
                item = await self._in_buff.get()
                if item is None:
                    break
                chunk, duration = item
                data += chunk
                length += duration
                if MAX_LENGTH_PER_REQUEST - length < CHUNK_DURATION * 2:
                    logging.debug(
                        f"yield data and return at {datetime.now().strftime('%H:%M:%S')}, the length is {length}")  # TODO, log debug
                    # stop reading data from buffer.
                    self._out_buff.put(copy.copy(data))
                    data = b""
                    length = 0
        finally:
            if length > 0:
                logging.debug('yield remaining data block')
                self._out_buff.put(copy.copy(data))
            self._out_buff.put(None)


class AudioTranscriber(QObject):
    finished = pyqtSignal()
    progress = pyqtSignal(str, bool)
    TO_FINISH_PLACE_HOLDER = "<span style='background-color: #ADD8E6;'>...</span>"

    def __init__(self, config: Dict[str, str]):
        super().__init__()
        self.language_code = config.get("LANGUAGE", "en")  # See https://cloud.google.com/speech-to-text/docs/languages
        self.config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=RATE,
            audio_channel_count=1,
            language_code=self.language_code,
            model='default',
            enable_automatic_punctuation=True,
        )

    def run(self):
        asyncio.run(self._run())

    def stop(self) -> None:
        """Called from the main GUI thread
        """
        def cleanup():
            self.progress.emit(self.TO_FINISH_PLACE_HOLDER, True)
            self.stream.stop()
        self.loop.call_soon_threadsafe(cleanup)

    async def _run(self) -> None:
        """Core method. start recording and transcribing audio into text. """
        audio_buffer: queue.Queue[bytes] = queue.Queue()  # audio data buffer
        text_queue: asyncio.Queue[str] = asyncio.Queue()  # transcribed text from audio

        def _callback(text):  # for _transcriber thread to write back
            self.loop.call_soon_threadsafe(text_queue.put_nowait,
                                           copy.copy(text) if text is not None else None)

        self.loop = asyncio.get_running_loop()
        self.stream = MicrophoneStream(RATE, CHUNK, audio_buffer)
        with self.stream:
            audio_generator = asyncio.create_task(self.stream.generate())
            transcriber = asyncio.create_task(asyncio.to_thread(self._transcribe, audio_buffer, _callback))
            copier = asyncio.create_task(self._copier(text_queue))

            await asyncio.wait(
                [audio_generator,  # open microphone and collect audio data
                 transcriber,  # transcribe audio into text
                 copier,  # read transcribed text
                 ],
                return_when=asyncio.ALL_COMPLETED
            )
        logging.debug('Transcriber is done and stopping.')
        self.finished.emit()

    async def _copier(self, text_queue: asyncio.Queue[str]) -> None:
        while text := await text_queue.get():
            logging.debug(f"write back {text}")
            self.progress.emit(text, False)

    def _transcribe(self, audio_buff: queue.Queue[bytes], callback: Callable[[str], None]):
        logging.debug(f"\nTranscribe thread started at {datetime.now().strftime('%H:%M:%S')}")
        with speech.SpeechClient() as client:
            try:
                while True:
                    content = audio_buff.get(timeout=MAX_LENGTH_PER_REQUEST)  # wait for data. blocking
                    if content is None:
                        break

                    audio = speech.RecognitionAudio(content=content)

                    logging.debug(f"start streaming recognize at {datetime.now().strftime('%H:%M:%S.%f')}")
                    response = client.recognize(config=self.config, audio=audio)
                    # time.sleep(3)
                    # callback("hello world....")

                    # Now, put the transcription responses to use.
                    logging.debug(f"start printing responses at {datetime.now().strftime('%H:%M:%S.%f')}")
                    if response.results:
                        result = response.results[0]
                        if result.alternatives:
                            callback(result.alternatives[0].transcript)
            finally:
                logging.debug(f"stopping transcribing audio data")
                callback(None)
