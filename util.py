from collections.abc import Callable, Iterable
from typing import TypeVar

T = TypeVar('T')
U = TypeVar('U')


def remove_unless(xs: list[T], f: Callable[[T], bool]) -> int:
    # https://stackoverflow.com/a/71528938/2690450
    w = 0
    for x in xs:
        if f(x):
            xs[w] = x
            w += 1
    del xs[w:]
    return w


def all_about_equal_floats(xs: Iterable[float], /, e=0.0001) -> bool:
    xs = iter(xs)
    x0 = next(xs)
    for x in xs:
        if abs(x - x0) > e:
            return False
    return True


def all_about_equal_elementwise(ts: Iterable[Iterable[T]], **kwargs) -> bool:
    ts = iter(ts)
    t0 = next(ts)
    for t in ts:
        for nth_elements in zip(t0, t):
            if not all_about_equal_floats(nth_elements, **kwargs):
                return False
    return True


def elementwise_sum(ts: Iterable[Iterable[T]]) -> Iterable[T]:
    return tuple(
        sum(nth_elements)
        for nth_elements in zip(*ts)
    )


def scalar_mul(a: T, xs: Iterable[T]) -> Iterable[T]:
    return tuple(a * x for x in xs)
