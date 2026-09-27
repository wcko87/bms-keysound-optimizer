import struct

class TYPE(object):
    char = '<c'
    signed_char = '<b'
    unsigned_char = '<B'
    bool = '?'
    short = '<h'
    unsigned_short = '<H'
    int = '<i'
    unsigned_int = '<I'
    long = '<l'
    unsigned_long = '<L'
    long_long = '<q'
    unsigned_long_long = '<Q'
    ssize_t = '<n'
    size_t = '<N'
    half_precision_float = '<e'
    float = '<f'
    double = '<d'
    float_complex = '<F'
    double_complex = '<D'

class Marker(object):
    def __init__(self, position, name):
        self.position = position
        self.name = name

    def __repr__(self):
        return rf'{self.position}|{self.name}'

class SypData(object):
    def __init__(self, file_path):
        syp = SypReader(file_path)
        self.offset = syp.read(TYPE.int)
        self.cursorPos = syp.read(TYPE.double)
        self.bpm = syp.read(TYPE.float)
        self.snapping = syp.read(TYPE.int)
        self.startingKeysound = syp.read(TYPE.int)
        self.useBase62 = syp.read(TYPE.bool)
        self.fadein = syp.read(TYPE.int)
        self.fadeout = syp.read(TYPE.int)
        self.selectedGateThreshold = syp.read(TYPE.int)
        self.selectedFile = syp.read_str()
        markers_size = syp.read(TYPE.unsigned_long_long)
        self.markers = []
        for i in range(markers_size):
            self.markers.append(Marker(
                position = syp.read(TYPE.double),
                name = syp.read_str(),
            ))
        self.keysoundOffsetEnd = syp.read(TYPE.int)

class SypReader():
    def __init__(self, file_path):
        with open(file_path, "rb") as f:
            self.data = f.read()
        self.offset = 0

    def read(self, format):
        data, offset = self.data, self.offset
        size = struct.calcsize(format)
        value = struct.unpack(format, data[offset:offset+size])[0]
        self.offset += size
        return value

    def read_str(self):
        str_len = self.read(TYPE.unsigned_long_long)
        data, offset = self.data, self.offset
        value = data[offset:offset + str_len].decode('utf-8')
        if value.endswith('\x00'):
            #print('cutting null byte at end of string')
            value = value[:-1]
        self.offset += str_len
        return value
