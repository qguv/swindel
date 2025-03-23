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


def about_equal(xs: Iterable[T], e=0.0001) -> bool:
    xs = iter(xs)
    x0 = next(xs)
    for x in xs:
        if abs(x - x0) > e:
            return False
    return True


def elements_about_equal(ts: Iterable[Iterable[T]], **kwargs) -> bool:
    ts = iter(ts)
    t0 = next(ts)
    for t in ts:
        for nth_elements in zip(t0, t):
            if not about_equal(nth_elements, **kwargs):
                return False
    return True


def elementwise_sum(ts: Iterable[Iterable[T]]) -> Iterable[T]:
    return tuple(
        sum(nth_elements)
        for nth_elements in zip(*ts)
    )


def scalar_mul(a: T, xs: Iterable[T]) -> Iterable[T]:
    return tuple(a * x for x in xs)


KeyT = TypeVar('KeyT')
OldValueT = TypeVar('OldValueT')
NewValueT = TypeVar('NewValueT')
def dmap(d: dict[KeyT, OldValueT], f: Callable[[OldValueT], NewValueT]) -> dict[KeyT, NewValueT]:
    return { k: f(v) for k, v in d.items() }


ValueT = TypeVar('ValueT')
def dmax_item(d: dict[KeyT, ValueT]):
    max_k = None
    max_v = None
    for k, v in d.items():
        if max_v is None or v > max_v:
            max_k = k
            max_v = v
    return max_k, max_v
