import hashlib

BMS_EXTENSIONS = ('.bms', '.bml', '.bms', '.pms')
SYP_EXTENSIONS = ('.syp',)
AUDIO_EXTENSIONS = ('.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a', '.wma')


BASE36_DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
def to_base36(n):
    original_n = n
    base36_str = ""
    while len(base36_str) < 2 or n > 0:
        n, r = divmod(n, 36)
        base36_str = BASE36_DIGITS[r] + base36_str
    if len(base36_str) > 2:
        print(f'WARNING - KEYSOUND EXCEEDING 2-DIGIT BASE36 LENGTH: {original_n} ({base36_str})')
    return base36_str

# fraction = 0.0 returns hex1, 1.0 returns hex2.
def blend_hex_colors(hex1, hex2, fraction):
    h1 = hex1.lstrip('#')
    h2 = hex2.lstrip('#')
    rgb = []
    for i in (0, 2, 4):
        val1 = int(h1[i:i+2], 16)
        val2 = int(h2[i:i+2], 16)
        blended_val = int(val1 + (val2 - val1) * fraction)
        rgb.append(blended_val)
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def compute_md5_hash(bms):
    byte_data = bms.to_string().encode('shift-jis')
    return hashlib.md5(byte_data).hexdigest()


def main():
    for i in [0,10,100,2000]:
        print(i, to_base36(i))


if __name__ == '__main__':
    main()