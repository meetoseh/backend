from dataclasses import dataclass
from decimal import Decimal
import math


@dataclass
class Size:
    width: int
    height: int


def get_useful_area(*, want: Size, have: Size) -> int:
    """Return how many useful pixels there are in an image of the `have` size if you will
    display it in the `want` size
    """
    effectively_have = Size(
        width=min(want.width, have.width),
        height=min(want.height, have.height),
    )
    return effectively_have.width * effectively_have.height


def get_useless_area(*, want: Size, have: Size) -> int:
    """Return how many useless pixels there are in an image of the `have` size if you will
    display it in the `want` size
    """
    return have.width * have.height - get_useful_area(want=want, have=have)


def compare_sizes(*, want: Size, a: Size, b: Size) -> int:
    """Returns a negative number if `a` is better than `b` for displaying in `want` size,
    a positive number if `b` is better, and 0 if they are equally good. Note that this ignores
    the effect of pixel ratios
    """
    useful_a = get_useful_area(want=want, have=a)
    useful_b = get_useful_area(want=want, have=b)
    if useful_a != useful_b:
        return useful_b - useful_a

    useless_a = get_useless_area(want=want, have=a)
    useless_b = get_useless_area(want=want, have=b)
    return useless_a - useless_b


def scale_lossily_via_pixel_ratio(size: Size, pixel_ratio: Decimal) -> Size:
    """Scales the given size by the given pixel ratio, rounding up to the nearest integer."""
    return Size(
        width=math.ceil(size.width * pixel_ratio),
        height=math.ceil(size.height * pixel_ratio),
    )


def get_effective_pixel_ratio(*, want: Size, device_pr: Decimal, have: Size) -> Decimal:
    """Given that you will display at a logical size of `want` on a device which has
    `device_pr` physical pixels per logical pixel, determines the effective pixel ratio
    for an image of size `have` after cropping.

    For example, if you want a 50x50 image on a 2x display, then a 500x500 image is
    effectively a 2x pixel ratio image since thats the best the display can render,
    i.e., it's no better than a 100x100 image.

    Only considers integer multiples of the device pixel ratio plus the logical size.
    So for a device pixel ratio of 3x we will consider 3x, 1.5x, (1x,) 0.75x, 0.375x, etc

    For performance, if the resulting pixel ratio is too small we return early.
    """
    if want.width <= 0 or want.height <= 0:
        raise ValueError("want.width and want.height must be positive")

    if device_pr >= 10:
        # prevents extremely long loops
        raise ValueError("device_pr must be less than 10 (performance)")

    # There's definitely a way to compute this without a loop

    pr = device_pr
    doing_1 = False
    while True:
        iteration_pr = Decimal(1) if doing_1 else pr
        want_at_pr = scale_lossily_via_pixel_ratio(want, iteration_pr)
        if have.width >= want_at_pr.width and have.height >= want_at_pr.height:
            return pr
        pr /= 2
        doing_1 = iteration_pr > 1 and pr < 1

        if pr < 0.3:
            # prevents extremely long loops
            return pr


def gcd(a: int, b: int) -> int:
    """Finds the greatest common divisor of two numbers using Euclid's algorithm"""
    while b:
        a, b = b, a % b
    return a
