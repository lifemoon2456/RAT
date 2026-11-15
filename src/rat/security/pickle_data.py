"""Bounded pickle *data* interpreter. No imports, constructors, reducers or game hooks run."""

import pickletools
import time
import zlib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Symbol:
    module: str
    name: str


@dataclass(eq=False)
class Record:
    symbol: Symbol
    args: tuple = ()
    state: object = None
    values: dict = field(default_factory=dict)
    mapping: dict = field(default_factory=dict)
    sequence: list = field(default_factory=list)


def inflate(data: bytes, *, limit: int) -> bytes:
    stream = zlib.decompressobj()
    result = stream.decompress(data, limit + 1)
    if len(result) > limit or stream.unconsumed_tail or not stream.eof or stream.unused_data:
        raise ValueError("compressed_data_limit_or_corruption")
    return result


class PickleDataReader:
    def __init__(self, *, records=False, max_ops=1000000, max_items=1000000, timeout=10):
        self.records, self.max_ops, self.timeout = records, max_ops, timeout
        self.max_items = max_items

    def read(self, data: bytes):
        stack, memo, mark = [], {}, object()
        started = time.monotonic()
        items = 0

        def consume(size):
            nonlocal items
            items += size
            if items > self.max_items:
                raise ValueError("pickle_container_resource_limit")

        def bounded_hash_value(value):
            pending, visited = [value], 0
            while pending:
                current = pending.pop()
                visited += 1
                if visited > 128:
                    raise ValueError("pickle_hash_resource_limit")
                if type(current) in {tuple, frozenset}:
                    if len(current) > 128:
                        raise ValueError("pickle_hash_resource_limit")
                    pending.extend(current)
                elif type(current) not in {str, bytes, int, float, bool, type(None)} and not (
                    self.records and isinstance(current, (Record, Symbol))
                ):
                    raise ValueError("invalid_pickle_key")

        def put_items(target, args):
            for key, value in zip(args[::2], args[1::2], strict=True):
                if not isinstance(key, (str, bytes, int, tuple)):
                    raise ValueError("invalid_pickle_key")
                bounded_hash_value(key)
                if not self.records and key in target:
                    raise ValueError("duplicate_pickle_index_key")
                target[key] = value

        def dictionary(args):
            result = {}
            put_items(result, args)
            return result

        def marked():
            for index in range(len(stack) - 1, -1, -1):
                if stack[index] is mark:
                    result = stack[index + 1 :]
                    del stack[index:]
                    return result
            raise ValueError("invalid_pickle_stack")

        def symbol(module, name):
            if type(module) is not str or type(name) is not str:
                raise ValueError("invalid_pickle_global")
            value = Symbol(module, name)
            primitives = {
                ("_codecs", "encode"),
                ("builtins", "set"),
                ("__builtin__", "set"),
                ("builtins", "frozenset"),
                ("__builtin__", "frozenset"),
                ("__builtin__", "bytes"),
                ("builtins", "bytes"),
                ("builtins", "list"),
                ("collections", "defaultdict"),
                ("collections", "OrderedDict"),
            }
            if (module, name) in primitives:
                return value
            if self.records and module.startswith("renpy.") and name.isidentifier():
                return value
            raise ValueError("unsafe_pickle_global")

        def construct(target, args, *, reduce=False):
            if not isinstance(target, Symbol) or type(args) is not tuple:
                raise ValueError("unsafe_pickle_constructor")
            key = (target.module, target.name)
            if key in {("__builtin__", "bytes"), ("builtins", "bytes")} and not args:
                return b""
            if key == ("_codecs", "encode"):
                if len(args) != 2 or type(args[0]) is not str or args[1] != "latin1":
                    raise ValueError("unsafe_pickle_reducer")
                return args[0].encode("latin1")
            if key in {
                ("builtins", "set"),
                ("__builtin__", "set"),
                ("builtins", "frozenset"),
                ("__builtin__", "frozenset"),
            }:
                if args:
                    if type(args[0]) not in {tuple, list, frozenset}:
                        raise ValueError("invalid_pickle_container")
                    consume(len(args[0]))
                    for value in args[0]:
                        bounded_hash_value(value)
                return frozenset(args[0]) if args else frozenset()
            if key == ("collections", "defaultdict"):
                if args != (Symbol("builtins", "list"),):
                    raise ValueError("unsafe_pickle_reducer")
                return {}
            if key == ("collections", "OrderedDict") and not args:
                return {}
            if self.records and target.module.startswith("renpy."):
                # Even REDUCE is represented as inert data; no target is called.
                return Record(target, args)
            raise ValueError("unsafe_pickle_reducer")

        try:
            for count, (operation, arg, position) in enumerate(pickletools.genops(data)):
                if count >= self.max_ops or len(stack) > 10000 or len(memo) > 250000:
                    raise ValueError("pickle_resource_limit")
                if count % 1024 == 0 and time.monotonic() - started > self.timeout:
                    raise ValueError("pickle_time_limit")
                op = operation.name
                if op in {"PROTO", "FRAME"}:
                    if op == "PROTO" and arg > 5:
                        raise ValueError("unsupported_pickle_protocol")
                elif op == "STOP":
                    if len(stack) != 1 or position != len(data) - 1:
                        raise ValueError("invalid_pickle_end")
                    return stack[0]
                elif op == "MARK":
                    stack.append(mark)
                elif op in {"NONE", "NEWTRUE", "NEWFALSE"}:
                    stack.append({"NONE": None, "NEWTRUE": True, "NEWFALSE": False}[op])
                elif op in {
                    "BININT",
                    "BININT1",
                    "BININT2",
                    "INT",
                    "LONG",
                    "LONG1",
                    "LONG4",
                    "FLOAT",
                    "BINFLOAT",
                    "UNICODE",
                    "BINUNICODE",
                    "SHORT_BINUNICODE",
                    "BINUNICODE8",
                    "BINBYTES",
                    "SHORT_BINBYTES",
                    "BINBYTES8",
                    "STRING",
                    "BINSTRING",
                    "SHORT_BINSTRING",
                }:
                    stack.append(arg)
                elif op == "EMPTY_DICT":
                    stack.append({})
                elif op == "EMPTY_LIST":
                    stack.append([])
                elif op == "EMPTY_TUPLE":
                    stack.append(())
                elif op in {"TUPLE1", "TUPLE2", "TUPLE3"}:
                    size = int(op[-1])
                    consume(size)
                    args = tuple(stack[-size:])
                    del stack[-size:]
                    stack.append(args)
                elif op in {"LIST", "TUPLE", "DICT", "FROZENSET"}:
                    args = marked()
                    consume(len(args))
                    if op == "FROZENSET":
                        for value in args:
                            bounded_hash_value(value)
                    stack.append(
                        list(args)
                        if op == "LIST"
                        else tuple(args)
                        if op == "TUPLE"
                        else frozenset(args)
                        if op == "FROZENSET"
                        else dictionary(args)
                    )
                elif op in {"SETITEM", "SETITEMS"}:
                    if op == "SETITEM":
                        value, key = stack.pop(), stack.pop()
                        args = [key, value]
                    else:
                        args = marked()
                    consume(len(args))
                    target = stack[-1]
                    if isinstance(target, Record) and target.symbol.name == "RevertableDict":
                        target = target.mapping
                    if type(target) is not dict:
                        raise ValueError("invalid_pickle_container")
                    put_items(target, args)
                elif op in {"APPEND", "APPENDS"}:
                    args = [stack.pop()] if op == "APPEND" else marked()
                    consume(len(args))
                    target = stack[-1]
                    if isinstance(target, Record) and target.symbol.name == "RevertableList":
                        target = target.sequence
                    if type(target) is not list:
                        raise ValueError("invalid_pickle_container")
                    target.extend(args)
                elif op in {"BINPUT", "LONG_BINPUT", "PUT", "MEMOIZE"}:
                    memo[len(memo) if op == "MEMOIZE" else int(arg)] = stack[-1]
                elif op in {"BINGET", "LONG_BINGET", "GET"}:
                    stack.append(memo[int(arg)])
                elif op in {"GLOBAL", "STACK_GLOBAL"}:
                    if op == "GLOBAL":
                        module, name = arg.split(" ", 1)
                    else:
                        name, module = stack.pop(), stack.pop()
                    stack.append(symbol(module, name))
                elif op in {"NEWOBJ", "REDUCE"}:
                    args, target = stack.pop(), stack.pop()
                    stack.append(construct(target, args, reduce=op == "REDUCE"))
                elif op == "BUILD":
                    state = stack.pop()
                    target = stack[-1]
                    if not isinstance(target, Record):
                        raise ValueError("unsafe_pickle_build")
                    target.state = state
                    states = state if type(state) is tuple and len(state) == 2 else (state,)
                    for values in states:
                        if type(values) is dict:
                            consume(len(values))
                            target.values.update(values)
                elif op == "POP":
                    stack.pop()
                elif op == "POP_MARK":
                    marked()
                elif op == "DUP":
                    stack.append(stack[-1])
                else:
                    raise ValueError("unsupported_or_unsafe_pickle_opcode:" + op)
        except (IndexError, KeyError, TypeError, OverflowError, RecursionError) as error:
            raise ValueError("malformed_pickle_data") from error
        raise ValueError("incomplete_pickle_data")
