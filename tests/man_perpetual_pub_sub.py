import asyncio
from perpetual_pub_sub import (
    PerpetualPubSub,
    PPSSubscription,
)


async def main():
    pps = PerpetualPubSub()

    async with PPSSubscription(pps, "ps:test", "test") as sub, PPSSubscription(
        pps, "ps:test2", "test2"
    ) as sub2:
        remaining = 4

        next_message_1 = asyncio.create_task(sub.read())
        next_message_2 = asyncio.create_task(sub2.read())

        while remaining:
            await asyncio.wait(
                [next_message_1, next_message_2],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if next_message_1.done():
                print("Message 1:", next_message_1.result())
                next_message_1 = asyncio.create_task(sub.read())
                remaining -= 1

            if next_message_2.done():
                print("Message 2:", next_message_2.result())
                next_message_2 = asyncio.create_task(sub2.read())
                remaining -= 1

        next_message_1.cancel()
        next_message_2.cancel()


if __name__ == "__main__":
    asyncio.run(main(), debug=True)
