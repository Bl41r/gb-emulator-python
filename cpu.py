"""The CPU.

The CPU in the original GameBoy is a modified Zilog Z80.

http://www.devrs.com/gb/files/opcodes.html :
The GameBoy has instructions & registers similiar to the 8080, 8085, & Z80
microprocessors. The internal 8-bit registers are A, B, C, D, E, F, H, & L.
Theses registers may be used in pairs for 16-bit operations as AF, BC, DE, &
HL. The two remaining 16-bit registers are the program counter (PC) and the
stack pointer (SP).

The F register holds the cpu flags. The operation of these flags is identical
to their Z80 relative. The lower four bits of this register always read zero
even if written with a one.

Flag Register
7   6   5   4   3   2   1   0
Z   N   H   C   0   0   0   0
The GameBoy CPU is based on a subset of the Z80 microprocessor.
A summary of these commands is given below.

Mnemonic    Symbolic Operation  Comments    CPU Clocks  Flags - Z,N,H,C
8-Bit Loads
-----------
LD r,s  r   s   s=r,n,(HL)  r=4, n=8, (HL)=8
LD d,r  d   r   d=r,(HL)    r=4, (HL)=8
LD d,n  d   n   r=8, (HL)=12
LD A,(ss)   A   (ss)    ss=BC,DE,HL,nn  [BC,DE,HL]=8, nn=16
LD (dd),A   (dd)   A    dd=BC,DE,HL,nn
LD A,(C)    A   ($FF00+C)   -   8
LD (C),A    ($FF00+C)   A   8
LDD A,(HL)  A   (HL), HL   HL - 1   8
LDD (HL),A  (HL)   A, HL   HL - 1   8
LDI A,(HL)  A   (HL), HL   HL + 1   8
LDI (HL),A  (HL)   A, HL   HL + 1   8
LDH (n),A   ($FF00+n)   A   12
LDH A,(n)   A   ($FF00+n)   12

16-Bit Loads
------------
LD dd,nn    dd   nn dd=BC,DE,HL,SP  12  -   -   -   -
LD (nn),SP  (nn)   SP   -   20
LD SP,HL    SP   HL 8
LD HL,(SP+e)    HL   (SP+e) 12  0   0   *   *
PUSH ss (SP-1)  ssh, (SP-2)  ssl, SPSP-2    ss=BC,DE,HL,AF  16  -   -   -   -
POP dd  ddl   (SP), ddh   (SP+1), SPSP+2    dd=BC,DE,HL,AF  12

8-Bit ALU
---------
ADD A,s A   A + s   CY is the carry flag. s=r,n,(HL)    r=4, n=8, (HL)=8    *   0   *   *
ADC A,s A   A + s + CY
SUB s   A   A - s   *   1   *   *
SBC A,s A   A - s - CY
AND s   A   A   s   *   0   1   0
OR s    A   A   s   *   0   0   0
XOR s   A   A   s
CP s    A - s   *   1   *   *
INC s   s   s + 1   s=r,(HL)    r=4, (HL)=12    *   0   *   -
DEC s   s   s - 1   *   1   *   -

16-Bit Arithmetic
-----------------
ADD HL,ss   HL   HL + ss    ss=BC,DE,HL,SP  8   -   0   *   *
ADD SP,e    SP   SP + e 16  0   0   *   *
INC ss  ss   ss + 1 8   -   -   -   -
DEC ss  ss   ss - 1 8

Miscellaneous
-------------
SWAP s      Swap nibbles. s=r,(HL)  r=8, (HL)=16    *   0   0   0
DAA Converts A into packed BCD. -   4   *   -   0   *
CPL A   /A  4   -   1   1   -
CCF CY  /CY CY is the carry flag.   4   -   0   0   *
SCF CY   1  4   -   0   0   1
NOP No operation.   -   4   -   -   -   -
HALT    Halt CPU until an interrupt occurs. 4
STOP    Halt CPU.   4
DI  Disable Interrupts. 4
EI  Enable Interrupts.  4

Rotates & Shifts
----------------
RLCA            4   0   0   0   *
RLA
RRCA
RRA
RLC s       s=A,r,(HL)  r=8,(HL)=16 *   0   0   *
RL s
RRC s
RR s
SLA s       s=r,(HL)    r=8, (HL)=16
SRA s
SRL s

Bit Opcodes
-----------
BIT b,s Z   /sb Z is zero flag. s=r,(HL)    r=8, (HL)=12    *   0   1   -
SET b,s sb   1  r=8, (HL)=16    -   -   -   -
RES b,s sb   0

Jumps
-----
JP nn   PC   nn -   16
JP cc,nn    If cc is true, PC   nn, else continue.  If cc is true, 16 else 12.
JP (HL) PC   HL 4
JR e    PC   PC + e 12
JR cc,e if cc is true, PC   PC + e, else continue.  If cc is true, 12 else 8.

Calls
-----
CALL nn (SP-1)   PCh, (SP-2)  PCl, PC  nn, SPSP-2   -   24
CALL cc,nn  If condition cc is false continue, else same as CALL nn.    If cc is true, 24 else 12.

Restarts
--------
RST f   (SP-1)   PCh, (SP-2)  PCl, PCh  0, PCl  f, SPSP-2   -   16

Returns
-------
RET pcl   (SP), pch   (SP+1), SPSP+2    -   16
RET cc  If cc is true, RET else continue.   If cc is true, 20 else 8.
RETI    Return then enable interrupts.  16

Terminology
-----------
-   Flag is not affected by this operation.
*   Flag is affected according to result of operation.
b   A bit number in any 8-bit register or memory location.
C   Carry flag.
cc  Flag condition code: C,NC,NZ,Z
d   Any 8-bit destination register or memory location.
dd  Any 16-bit destination register or memory location.
e   8-bit signed 2's complement displacement.
f   8 special call locations in page zero.
H   Half-carry flag.
N   Subtraction flag.
NC  Not carry flag
NZ  Not zero flag.
n   Any 8-bit binary number.
nn  Any 16-bit binary number.
r   Any 8-bit register. (A,B,C,D,E,H, or L)
s   Any 8-bit source register or memory location.
sb  A bit in a specific 8-bit register or memory location.
ss  Any 16-bit source register or memory location.
Z   Zero Flag.
"""

FLAG_BITS = {
    'zero': 0x80,           # Z flag
    'subtraction': 0x40,    # N flag
    'half-carry': 0x20,     # H flag
    'carry': 0x10           # C flag
}


class Z80Cpu(object):
    """The Z80 CPU class."""

    def __init__(self, memory):
        """Initialize an instance."""
        self.clock = {'m': 0, 't': 0}  # Time clocks: 2 types of clock

        self.memory = memory

        # Register set
        self.registers = {
            # 8-bit registers
            'a': 0, 'b': 0, 'c': 0, 'd': 0, 'e': 0, 'h': 0, 'l': 0,
            # 8-bit 'flag' register
            'flag': 0,
            # 16-bit registers (program counter, stack pointer)
            'pc': 0, 'sp': 0,
            # Clock for last instr
            'm': 0, 't': 0
        }

        self.opcode_map = {
            # opcode number: func to call, args
            0: (self._nop, []),  # NOP
            1: ('', []),  # LDBCnn
            2: (self._ld_r1r2m_a, ['b', 'c']),  # LDBCmA
            3: ('', []),  # INCBC
            4: ('', []),  # INCr_b
            5: ('', []),  # DECr_b
            6: (self._ld_rn, ['b']),  # LDrn_b
            7: ('', []),  # RLCA
            8: ('', []),  # LDmmSP
            9: ('', []),  # ADDHLBC
            10: (self._ld_a_r1r2m, ['b', 'c']),  # LDABCm
            11: ('', []),  # DECBC
            12: ('', []),  # INCr_c
            13: ('', []),  # DECr_c
            14: (self._ld_rn, ['c']),  # LDrn_c
            15: ('', []),  # RRCA
            16: ('', []),  # DJNZn
            17: ('', []),  # LDDEnn
            18: (self._ld_r1r2m_a, ['d', 'e']),  # LDDEmA
            19: ('', []),  # INCDE
            20: ('', []),  # INCr_d
            21: ('', []),  # DECr_d
            22: (self._ld_rn, ['d']),  # LDrn_d
            23: ('', []),  # RLA
            24: ('', []),  # JRn
            25: ('', []),  # ADDHLDE
            26: (self._ld_a_r1r2m, ['d', 'e']),  # LDADEm
            27: ('', []),  # DECDE
            28: ('', []),  # INCr_e
            29: ('', []),  # DECr_e
            30: (self._ld_rn, ['e']),  # LDrn_e
            31: ('', []),  # RRA
            32: ('', []),  # JRNZn
            33: ('', []),  # LDHLnn
            34: ('', []),  # LDHLIA
            35: ('', []),  # INCHL
            36: ('', []),  # INCr_h
            37: ('', []),  # DECr_h
            38: (self._ld_rn, ['h']),  # LDrn_h
            39: ('', []),  # XX
            40: ('', []),  # JRZn
            41: ('', []),  # ADDHLHL
            42: ('', []),  # LDAHLI
            43: ('', []),  # DECHL
            44: ('', []),  # INCr_l
            45: ('', []),  # DECr_l
            46: (self._ld_rn, ['l']),  # LDrn_l
            47: ('', []),  # CPL
            48: ('', []),  # JRNCn
            49: ('', []),  # LDSPnn
            50: ('', []),  # LDHLDA
            51: ('', []),  # INCSP
            52: ('', []),  # INCHLm
            53: ('', []),  # DECHLm
            54: (self._ld_hlm_n, []),  # LDHLmn
            55: ('', []),  # SCF
            56: ('', []),  # JRCn
            57: ('', []),  # ADDHLSP
            58: ('', []),  # LDAHLD
            59: ('', []),  # DECSP
            60: ('', []),  # INCr_a
            61: ('', []),  # DECr_a
            62: (self._ld_rn, ['a']),  # LDrn_a
            63: ('', []),  # CCF
            64: (self._ld_rr, ['b', 'b']),  # LDrr_bb (nop?)
            65: (self._ld_rr, ['b', 'c']),  # LDrr_bc
            66: (self._ld_rr, ['b', 'd']),  # LDrr_bd
            67: (self._ld_rr, ['b', 'e']),  # LDrr_be
            68: (self._ld_rr, ['b', 'h']),  # LDrr_bh
            69: (self._ld_rr, ['b', 'l']),  # LDrr_bl
            70: (self._ld_r_hlm, ['b']),  # LDrHLm_b
            71: (self._ld_rr, ['b', 'a']),  # LDrr_ba
            72: (self._ld_rr, ['c', 'b']),  # LDrr_cb
            73: (self._ld_rr, ['c', 'c']),  # LDrr_cc (nop?)
            74: (self._ld_rr, ['c', 'd']),  # LDrr_cd
            75: (self._ld_rr, ['c', 'e']),  # LDrr_ce
            76: (self._ld_rr, ['c', 'h']),  # LDrr_ch
            77: (self._ld_rr, ['c', 'l']),  # LDrr_cl
            78: (self._ld_r_hlm, ['c']),  # LDrHLm_c
            79: (self._ld_rr, ['c', 'a']),  # LDrr_ca
            80: (self._ld_rr, ['d', 'b']),  # LDrr_db
            81: (self._ld_rr, ['d', 'c']),  # LDrr_dc
            82: (self._ld_rr, ['d', 'd']),  # LDrr_dd (nop?)
            83: (self._ld_rr, ['d', 'e']),  # LDrr_de
            84: (self._ld_rr, ['d', 'h']),  # LDrr_dh
            85: (self._ld_rr, ['d', 'l']),  # LDrr_dl
            86: (self._ld_r_hlm, ['d']),  # LDrHLm_d
            87: (self._ld_rr, ['d', 'a']),  # LDrr_da
            88: (self._ld_rr, ['e', 'b']),  # LDrr_eb
            89: (self._ld_rr, ['e', 'c']),  # LDrr_ec
            90: (self._ld_rr, ['e', 'd']),  # LDrr_ed
            91: (self._ld_rr, ['e', 'e']),  # LDrr_ee (nop?)
            92: (self._ld_rr, ['e', 'h']),  # LDrr_eh
            93: (self._ld_rr, ['e', 'l']),  # LDrr_el
            94: (self._ld_r_hlm, ['e']),  # LDrHLm_e
            95: (self._ld_rr, ['e', 'a']),  # LDrr_ea
            96: (self._ld_rr, ['h', 'b']),  # LDrr_hb
            97: (self._ld_rr, ['h', 'c']),  # LDrr_hc
            98: (self._ld_rr, ['h', 'd']),  # LDrr_hd
            99: (self._ld_rr, ['h', 'e']),  # LDrr_he
            100: (self._ld_rr, ['h', 'h']),  # LDrr_hh (nop?)
            101: (self._ld_rr, ['h', 'l']),  # LDrr_hl
            102: (self._ld_r_hlm, ['h']),  # LDrHLm_h
            103: (self._ld_rr, ['h', 'a']),  # LDrr_ha
            104: (self._ld_rr, ['l', 'b']),  # LDrr_lb
            105: (self._ld_rr, ['l', 'c']),  # LDrr_lc
            106: (self._ld_rr, ['l', 'd']),  # LDrr_ld
            107: (self._ld_rr, ['l', 'e']),  # LDrr_le
            108: (self._ld_rr, ['l', 'h']),  # LDrr_lh
            109: (self._ld_rr, ['l', 'l']),  # LDrr_ll (nop?)
            110: (self._ld_r_hlm, ['l']),  # LDrHLm_l
            111: (self._ld_rr, ['l', 'a']),  # LDrr_la
            112: (self._ld_hlm_r, ['b']),  # LDHLmr_b
            113: (self._ld_hlm_r, ['c']),  # LDHLmr_c
            114: (self._ld_hlm_r, ['d']),  # LDHLmr_d
            115: (self._ld_hlm_r, ['e']),  # LDHLmr_e
            116: (self._ld_hlm_r, ['h']),  # LDHLmr_h
            117: (self._ld_hlm_r, ['l']),  # LDHLmr_l
            118: ('', []),  # HALT
            119: (self._ld_hlm_r, ['a']),  # LDHLmr_a
            120: (self._ld_rr, ['a', 'b']),  # LDrr_ab
            121: (self._ld_rr, ['a', 'c']),  # LDrr_ac
            122: (self._ld_rr, ['a', 'd']),  # LDrr_ad
            123: (self._ld_rr, ['a', 'e']),  # LDrr_ae
            124: (self._ld_rr, ['a', 'h']),  # LDrr_ah
            125: (self._ld_rr, ['a', 'l']),  # LDrr_al
            126: (self._ld_r_hlm, ['a']),  # LDrHLm_a
            127: (self._ld_rr, ['a', 'a']),  # LDrr_aa (nop?)
            128: ('', []),  # ADDr_b
            129: ('', []),  # ADDr_c
            130: ('', []),  # ADDr_d
            131: ('', []),  # ADDr_e
            132: ('', []),  # ADDr_h
            133: ('', []),  # ADDr_l
            134: ('', []),  # ADDHL
            135: ('', []),  # ADDr_a
            136: ('', []),  # ADCr_b
            137: ('', []),  # ADCr_c
            138: ('', []),  # ADCr_d
            139: ('', []),  # ADCr_e
            140: ('', []),  # ADCr_h
            141: ('', []),  # ADCr_l
            142: ('', []),  # ADCHL
            143: ('', []),  # ADCr_a
            144: ('', []),  # SUBr_b
            145: ('', []),  # SUBr_c
            146: ('', []),  # SUBr_d
            147: ('', []),  # SUBr_e
            148: ('', []),  # SUBr_h
            149: ('', []),  # SUBr_l
            150: ('', []),  # SUBHL
            151: ('', []),  # SUBr_a
            152: ('', []),  # SBCr_b
            153: ('', []),  # SBCr_c
            154: ('', []),  # SBCr_d
            155: ('', []),  # SBCr_e
            156: ('', []),  # SBCr_h
            157: ('', []),  # SBCr_l
            158: ('', []),  # SBCHL
            159: ('', []),  # SBCr_a
            160: ('', []),  # ANDr_b
            161: ('', []),  # ANDr_c
            162: ('', []),  # ANDr_d
            163: ('', []),  # ANDr_e
            164: ('', []),  # ANDr_h
            165: ('', []),  # ANDr_l
            166: ('', []),  # ANDHL
            167: ('', []),  # ANDr_a
            168: ('', []),  # XORr_b
            169: ('', []),  # XORr_c
            170: ('', []),  # XORr_d
            171: ('', []),  # XORr_e
            172: ('', []),  # XORr_h
            173: ('', []),  # XORr_l
            174: ('', []),  # XORHL
            175: ('', []),  # XORr_a
            176: ('', []),  # ORr_b
            177: ('', []),  # ORr_c
            178: ('', []),  # ORr_d
            179: ('', []),  # ORr_e
            180: ('', []),  # ORr_h
            181: ('', []),  # ORr_l
            182: ('', []),  # ORHL
            183: ('', []),  # ORr_a
            184: ('', []),  # CPr_b
            185: ('', []),  # CPr_c
            186: ('', []),  # CPr_d
            187: ('', []),  # CPr_e
            188: ('', []),  # CPr_h
            189: ('', []),  # CPr_l
            190: ('', []),  # CPHL
            191: ('', []),  # CPr_a
            192: ('', []),  # RETNZ
            193: ('', []),  # POPBC
            194: ('', []),  # JPNZnn
            195: ('', []),  # JPnn
            196: ('', []),  # CALLNZnn
            197: ('', []),  # PUSHBC
            198: ('', []),  # ADDn
            199: ('', []),  # RST00
            200: ('', []),  # RETZ
            201: ('', []),  # RET
            202: ('', []),  # JPZnn
            203: ('', []),  # MAPcb
            204: ('', []),  # CALLZnn
            205: ('', []),  # CALLnn
            206: ('', []),  # ADCn
            207: ('', []),  # RST08
            208: ('', []),  # RETNC
            209: ('', []),  # POPDE
            210: ('', []),  # JPNCnn
            211: ('', []),  # XX
            212: ('', []),  # CALLNCnn
            213: ('', []),  # PUSHDE
            214: ('', []),  # SUBn
            215: ('', []),  # RST10
            216: ('', []),  # RETC
            217: ('', []),  # RETI
            218: ('', []),  # JPCnn
            219: ('', []),  # XX
            220: ('', []),  # CALLCnn
            221: ('', []),  # XX
            222: ('', []),  # SBCn
            223: ('', []),  # RST18
            224: ('', []),  # LDIOnA
            225: ('', []),  # POPHL
            226: ('', []),  # LDIOCA
            227: ('', []),  # XX
            228: ('', []),  # XX
            229: ('', []),  # PUSHHL
            230: ('', []),  # ANDn
            231: ('', []),  # RST20
            232: ('', []),  # ADDSPn
            233: ('', []),  # JPHL
            234: (self._ld_mm_a, []),  # LDmmA
            235: ('', []),  # XX
            236: ('', []),  # XX
            237: ('', []),  # XX
            238: ('', []),  # ORn
            239: ('', []),  # RST28
            240: ('', []),  # LDAIOn
            241: ('', []),  # POPAF
            242: ('', []),  # LDAIOC
            243: ('', []),  # DI
            244: ('', []),  # XX
            245: ('', []),  # PUSHAF
            246: ('', []),  # XORn
            247: ('', []),  # RST30
            248: ('', []),  # LDHLSPn
            249: ('', []),  # XX
            250: (self._ld_a_mm, []),  # LDAmm
            251: ('', []),  # EI
            252: ('', []),  # XX
            253: ('', []),  # XX
            254: ('', []),  # CPn
            255: ('', []),  # RST38
        }

    def execute_next_operation(self):
        """Execute the next operation."""
        op = self.read8(self.registers['pc'])
        self.registers['pc'] += 1
        self.registers['pc'] &= 65535   # mask to 16-bits
        instruction = self.opcode_map[op]
        print(instruction)
        opcode, args = instruction[0], instruction[1]
        opcode(*args)
        self._inc_clock()

    def execute_specific_instruction(self, op):
        """Execute an instruction (for testing)."""
        instruction = self.opcode_map[op]
        print(instruction)
        opcode, args = instruction[0], instruction[1]
        opcode(*args)
        self._inc_clock()

    def reset(self):
        """Reset registers."""
        for k in self.clock.items():
            self.clock[k] = 0
        for k in self.registers.items():
            self.registers[k] = 0

    def read8(self, address):
        """Return a byte from memory at address."""
        return self.memory.read_byte(address)

    def write8(self, address, val):
        """Write a byte to memory at address."""
        self.memory.write_byte(address, val)

    def read16(self, address):
        """Return a word(16-bits) from memory."""
        return self.memory.read_word(address)

    def write16(self, address, val):
        """Write a word to memory at address."""
        self.memory.write_word(address, val)

    def _inc_clock(self):
        """Increment clock registers."""
        self.clock['m'] += self.registers['m']
        self.clock['t'] += self.registers['t']

    # Opcodes
    def _nop(self):
        """NOP opcode."""
        self.registers['m'] = 1
        self.registers['t'] = 4

    # Loads
    def _ld_rr(self, r1, r2):
        """Load value r2 into r1."""
        self.registers[r1] = self.registers[r2]
        self.registers['m'] = 1
        self.registers['t'] = 4
        print('yo', r1, r2)

    def _ld_rn(self, r):
        """Load mem @ pc into register r."""
        self.registers[r] = self.read8(self.registers['pc'])
        self.registers['pc'] += 1
        self.registers['m'] = 2
        self.registers['t'] = 8

    def _ld_r_hlm(self, r):
        """Load mem @ HL into registers[r]."""
        read_byte = self.read8((self.registers['h'] << 8) + self.registers['l'])
        self.registers[r] = read_byte
        self.registers['m'] = 2
        self.registers['t'] = 8

    def _ld_hlm_r(self, r):
        """Load registers[r] into mem @ HL."""
        write_address = (self.registers['h'] << 8) + self.registers['l']
        self.write8(write_address, self.registers[r])
        self.registers['m'] = 2
        self.registers['t'] = 8

    def _ld_hlm_n(self):
        """Load mem @ pc into mem @ HL."""
        write_address = (self.registers['h'] << 8) + self.registers['l']
        self.write8(write_address, self.registers['pc'])
        self.registers['pc'] += 1
        self.registers['m'] = 3
        self.registers['t'] = 12

    def _ld_r1r2m_a(self, r1, r2):
        """Load registers[a] into mem @ BC."""
        write_address = (self.registers[r1] << 8) + self.registers[r2]
        self.write8(write_address, self.registers['a'])
        self.registers['m'] = 2
        self.registers['t'] = 8

    def _ld_mm_a(self):
        """Load byte registers['a'] into mem @ 16-bit address.

        address = mem @ registers[pc]
        """
        self.write8(self.read16(self.registers['pc']), self.registers['a'])
        self.registers['pc'] += 2
        self.registers['m'] = 4
        self.registers['t'] = 16

    def _ld_a_r1r2m(self, r1, r2):
        """Load mem @ r1r2 into registers[a]."""
        address = (self.registers[r1] << 8) + self.registers[r2]
        self.registers['a'] = self.read8(address)
        self.registers['m'] = 2
        self.registers['t'] = 8

    def _ld_a_mm(self):
        """Load byte into registers[a].

        byte = mem(byte) @ mem(word) @ registers[pc]
        """
        self.registers['a'] = self.read8(self.read16(self.registers['pc']))
        self.registers['pc'] += 2
        self.registers['m'] = 4
        self.registers['t'] = 16










