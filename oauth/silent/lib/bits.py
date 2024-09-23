from typing import Optional, Union, overload


class Bits:
    """Like bytes, but when the primary operations are on bits rather than bytes"""

    def __init__(self, length: int):
        self.length: int = length
        """The actual length of this bit string"""
        self.data: bytearray = bytearray((length + 7) // 8)
        """The data storing the bit string with up to 7 unnecessary trailing bits"""

    @classmethod
    def from_data(cls, data: bytearray, /, *, length: Optional[int] = None) -> "Bits":
        """Returns a new bit string with the given data and length. If length is
        omitted, it is assumed to be the length of the data in bits"""
        num_bytes = len(data)
        if length is None:
            length = num_bytes * 8

        if length < (num_bytes - 1) * 8:
            raise ValueError(
                f"Expected a length of at least {(num_bytes - 1) * 8} bits given {len(data)} bytes, but got {length}"
            )
        if length > num_bytes * 8:
            raise ValueError(
                f"Expected a length of at most {num_bytes * 8} bits given {len(data)} bytes, but got {length}"
            )

        result = cls(0)
        result.data = data
        result.length = length
        return result

    @classmethod
    def from_other(cls, other: "Bits") -> "Bits":
        """Returns a copy of other"""
        result = cls(other.length)
        result[:] = other
        return result

    @classmethod
    def concat(cls, a: "Bits", b: "Bits") -> "Bits":
        """Returns a new bit string that is the concatenation of a and b"""
        result = cls(len(a) + len(b))
        result[: len(a)] = a
        result[len(a) :] = b
        return result

    @classmethod
    def concat_many(cls, a: "Bits", *rest: "Bits") -> "Bits":
        """Returns a new bit string that is the concatenation of a and the rest"""
        result = cls(len(a) + sum(len(b) for b in rest))
        result[: len(a)] = a
        offset = len(a)
        for b in rest:
            result[offset : offset + len(b)] = b
            offset += len(b)
        return result

    @classmethod
    def xor(cls, a: "Bits", b: "Bits", /, *, into: Optional["Bits"] = None) -> "Bits":
        """Returns a new bit string that is the xor of a and b"""
        # PERF: obviously, performance can be improved here
        if len(a) != len(b):
            raise ValueError(
                f"Expected two bit strings of the same length, but got {len(a)} and {len(b)}"
            )

        if into is None:
            into = cls(len(a))

        if len(into) != len(a):
            raise ValueError(
                f"Expected the result bit string to have length {len(a)}, but got {len(into)}"
            )

        for i in range(len(a)):
            into[i] = a[i] != b[i]
        return into

    def as_bytes(self) -> bytes:
        if self.length % 8 != 0:
            raise ValueError(f"Expected a multiple of 8 bits, but got {self.length}")
        return bytes(self.data)

    def __len__(self) -> int:
        return self.length

    @overload
    def __getitem__(self, index: int) -> bool: ...

    @overload
    def __getitem__(self, index: slice) -> "Bits": ...

    def __getitem__(self, index: Union[int, slice]) -> Union["Bits", bool]:
        if isinstance(index, int):
            return ((self.data[index // 8] >> (7 - (index % 8))) & 1) == 1

        if (
            index.start is None
            and index.stop is None
            and (index.step is None or index.step == 1)
        ):
            return Bits.from_other(self)

        start = index.start or 0
        stop = index.stop or self.length
        step = index.step or 1

        result = Bits((stop - start + step - 1) // step)
        for i in range(start, stop, step):
            result[i - start] = self[i]
        return result

    @overload
    def __setitem__(self, index: int, value: bool): ...

    @overload
    def __setitem__(self, index: slice, value: "Bits"): ...

    def __setitem__(self, index: Union[int, slice], value: Union[bool, "Bits"]):
        if isinstance(index, int):
            if value not in (True, False):
                raise ValueError(
                    f"Expected a boolean value for int index, but got {value}"
                )
            if value:
                self.data[index // 8] |= 1 << (7 - (index % 8))
            else:
                self.data[index // 8] &= ~(1 << (7 - (index % 8)))
            return

        if not isinstance(value, Bits):
            raise ValueError(f"Expected a Bits object for slice index, but got {value}")

        if (
            index.start is None
            and index.stop is None
            and (index.step is None or index.step == 1)
        ):
            if len(value) != self.length:
                raise ValueError(
                    f"Expected a Bits object of length {self.length}, but got {len(value)}"
                )
            self.data = value.data.copy()
            return

        start = index.start or 0
        stop = index.stop or self.length
        step = index.step or 1

        if len(value) != (stop - start + step - 1) // step:
            raise ValueError(
                f"Expected a Bits object of length {(stop - start + step - 1) // step}, but got {len(value)}"
            )

        for i in range(start, stop, step):
            self[i] = value[i - start]
