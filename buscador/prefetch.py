"""Lê os próximos arquivos do disco em paralelo enquanto a placa de vídeo trabalha no atual."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, Iterator, TypeVar

T = TypeVar("T")


def ahead(items: Iterable[T], load: Callable[[T], object], workers: int = 3, depth: int = 6,
          stop=None) -> Iterator[tuple[T, object]]:
    """Devolve (item, resultado de load(item)) na ordem original; se load falhar, o resultado é a exceção."""
    def safe(it):
        try:
            return load(it)
        except Exception as exc:
            return exc

    it = iter(items)
    pending: deque = deque()
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="leitura") as pool:
        for x in it:
            pending.append((x, pool.submit(safe, x)))
            if len(pending) >= depth:
                break
        while pending:
            x, fut = pending.popleft()
            res = fut.result()
            if stop is not None and stop.is_set():
                for _, f in pending:
                    f.cancel()
                return
            nxt = next(it, None)
            if nxt is not None:
                pending.append((nxt, pool.submit(safe, nxt)))
            yield x, res
