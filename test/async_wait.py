import asyncio
import contextlib


async def waiter(event):
    print('waiting for it ...')
    await event.wait()
    print('... got it!')


async def printer():
    while True:
        print('printer running')
        await asyncio.sleep(0.5)


async def main():
    # Create an Event object.
    event = asyncio.Event()

    # Spawn a Task to wait until 'event' is set.
    waiter_task = asyncio.create_task(waiter(event))
    printer_task = asyncio.create_task(printer())

    # Sleep for 1 second and set the event.
    await asyncio.sleep(1)
    event.set()
    printer_task.cancel()

    # Wait until the waiter task is finished.
    await waiter_task
    with contextlib.suppress(asyncio.CancelledError):
        await printer_task
    print('done')


asyncio.run(main())