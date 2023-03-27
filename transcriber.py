from __future__ import annotations
from typing import *

import functools

import asyncio
import copy
import logging
import queue
from datetime import datetime

import pyaudio
from PyQt6.QtCore import QObject, pyqtSignal

# Audio recording parameters
# A frame is a set of samples that occur simultaneously. For a stereo stream, a frame is two samples.
RATE = 16000  # sampling rate, the number of frames per second
CHUNK = 1024  # frames per buffer.
CHUNK_DURATION = CHUNK / RATE  # the duration of a chunk

# Google charges each request rounded up to the nearest increment of 15 seconds
# We limit each request no more than but close to 15 seconds
MAX_LENGTH_PER_REQUEST = 30


class MicrophoneStream:
    """Opens a recording stream and store the audio chunks in an output buffer."""

    def __init__(self, rate: int, chunk: int, out_buff: queue.Queue[bytes]):
        self._rate = rate
        self._chunk = chunk
        self._closed = True  # stream status flag
        self._in_buff: asyncio.Queue[bytes] = asyncio.Queue()  # in audio bytes from microphone
        self._out_buff = out_buff  # out audio bytes buffer

    def __enter__(self):
        loop = asyncio.get_running_loop()
        # documentation https://people.csail.mit.edu/hubert/pyaudio/docs/#pyaudio.PyAudio.Stream.__init__
        self._pyaudio = pyaudio.PyAudio()
        self._audio_stream = self._pyaudio.open(
            format=pyaudio.paInt16,  # Sampling size and format
            channels=1,  # Number of channels
            rate=self._rate,  # Sampling rate
            input=True,  # Specifies whether this is an input stream
            output=False,  # Specifies whether this is an output stream.
            frames_per_buffer=self._chunk,  # Specifies the number of frames per buffer
            stream_callback=functools.partial(self._fill_buffer, loop),
        )
        self._closed = False
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._audio_stream.stop_stream()
        self._audio_stream.close()
        self._pyaudio.terminate()
        self._closed = True

    def stop(self) -> None:
        logging.debug('stopping microphone...')
        self._in_buff.put_nowait(None)

    def _fill_buffer(self, loop, in_data: bytes, frame_count: int, time_info: Mapping[str, float],
                     status_flags: int) -> (None, int):
        """Call back function to continuously collect data from the audio stream into the buffer.
        This will be called from the Microphone recording thread.

        see http://people.csail.mit.edu/hubert/pyaudio/docs/#pyaudio.Stream.__init__
        for the signature of callback function.
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

    async def collect(self) -> None:
        """Called to read audio data from microphone into output buffer. """
        logging.debug(f"\nData generation started at {datetime.now().strftime('%H:%M:%S')}")
        length = 0  # in seconds
        data = bytearray()
        try:
            while True:
                item = await self._in_buff.get()
                if item is None:
                    break
                chunk, duration = item
                data.extend(chunk)
                length += duration

                # no more space for another chunk, yield data
                if MAX_LENGTH_PER_REQUEST - length <= CHUNK_DURATION:
                    logging.debug(
                        f"yield data at {datetime.now().strftime('%H:%M:%S')}, the duration is {length}")
                    self._out_buff.put(bytes(data))
                    data.clear()
                    length = 0
        finally:
            if length > 0:
                logging.debug('yield remaining data block')
                self._out_buff.put(bytes(data))
            self._out_buff.put(None)


class AudioTranscriber(QObject):
    finished = pyqtSignal()
    progress = pyqtSignal(str, bool)
    TO_FINISH_PLACE_HOLDER = "<span style='background-color: #ADD8E6;'>...</span>"

    def __init__(self, config: Dict[str, str]):
        super().__init__()
        self.language_code = config.get("LANGUAGE", "en")

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
        audio_buffer: queue.Queue[bytes] = queue.Queue()  # audio data out buffer
        text_queue: asyncio.Queue[str] = asyncio.Queue()  # transcribed text out buffer

        def _callback(text):  # for _transcriber thread to write back
            self.loop.call_soon_threadsafe(text_queue.put_nowait,
                                           copy.copy(text) if not text else None)

        self.loop = asyncio.get_running_loop()
        self.stream = MicrophoneStream(RATE, CHUNK, audio_buffer)
        with self.stream:
            audio_generator = asyncio.create_task(self.stream.collect())
            transcriber = self.loop.run_in_executor(self._transcribe, audio_buffer, _callback)
            copier = asyncio.create_task(self._copier(text_queue))

            await asyncio.wait((
                audio_generator,  # open microphone and collect audio data
                transcriber,  # transcribe audio into text
                copier,  # read transcribed text
            ),
                return_when=asyncio.ALL_COMPLETED
            )
        self.finished.emit()
        logging.debug('Transcriber is done and stopping.')

    async def _copier(self, text_queue: asyncio.Queue[str]) -> None:
        while text := await text_queue.get():
            logging.debug(f"write back {text}")
            self.progress.emit(text, False)

    def _transcribe(self, audio_buff: queue.Queue[bytes], callback: Callable[[str], None]):
        """Call Google speech API to transcribe audio data into text. """
        logging.debug(f"\nTranscribe thread started at {datetime.now().strftime('%H:%M:%S')}")
        # to finish
