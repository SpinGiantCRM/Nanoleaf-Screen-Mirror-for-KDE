/* Offline checksum hypothesis search. No files, USB or network. */
#include <stdint.h>
#include <stdio.h>
static uint16_t effect(uint16_t polynomial, int reflected, uint8_t first) {
    uint16_t c = reflected ? first : (uint16_t)first << 8;
    for (int bit = 0; bit < 59 * 8; ++bit) {
        if (reflected) c = (uint16_t)((c >> 1) ^ ((c & 1) ? polynomial : 0));
        else c = (uint16_t)((c << 1) ^ ((c & 0x8000) ? polynomial : 0));
    }
    return c;
}
int main(void) {
    unsigned matches = 0;
    for (int reflected = 0; reflected <= 1; ++reflected) {
        for (unsigned p = 1; p <= 65535; ++p) {
            uint16_t a = effect((uint16_t)p, reflected, 3);
            uint16_t b = effect((uint16_t)p, reflected, 7);
            if (a == 0x03f0 && b == 0x06b0) {
                printf("polynomial=0x%04x reflected=%d trailer=big\n",p,reflected); ++matches;
            }
            if (a == 0xf003 && b == 0xb006) {
                printf("polynomial=0x%04x reflected=%d trailer=little\n",p,reflected); ++matches;
            }
        }
    }
    printf("matches=%u\n", matches);
}
