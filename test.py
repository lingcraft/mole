from mole import Packet, get_int
from pendulum import duration


def get_input(tip: str):
    print(f"请输入{tip}：")
    return [bytes.fromhex(line) for line in iter(lambda: input(), "")]


def result(operate, lines):
    return "\n".join([operate(line) for line in lines])


def decrypt():
    lines = get_input("封包密文")
    operate = lambda line: Packet(line).decrypt().data().hex().upper()
    return result(operate, lines)


def decode():
    lines = get_input("需要解码数据")
    operate = lambda line: line.rstrip(b'\x00').decode()
    return result(operate, lines)


def format_seconds():
    lines = get_input("总秒数")
    operate = lambda line: duration(seconds=get_int(line)).in_words(locale="zh")
    return result(operate, lines)


if __name__ == '__main__':
    while True:
        func = decrypt
        print(f"结果：\n{func()}\n")
