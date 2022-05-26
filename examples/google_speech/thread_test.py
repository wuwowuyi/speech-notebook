import asyncio
import queue
import time


out = queue.Queue()

async def generate():
    print(f"started generate at {time.strftime('%X')}")
    for i in range(3):
        await asyncio.sleep(1)
        out.put(i)
    out.put(None)


def blocking_io(num):
    print(f"start blocking_io at {time.strftime('%X')}")
    while True:
        # Note that time.sleep() can be replaced with any blocking
        # IO-bound operation, such as file operations.
        item = out.get()
        if item is None:
            print('queue is emtpy. terminate.')
            break
        print(item)
        time.sleep(num)
    print(f"blocking_io complete at {time.strftime('%X')}")


async def main():
    print(f"started main at {time.strftime('%X')}")
    await asyncio.gather(
        generate(),
        asyncio.to_thread(blocking_io, 2))

    print(f"finished main at {time.strftime('%X')}")

asyncio.run(main())
