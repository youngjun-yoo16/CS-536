#include <sys/socket.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <linux/tcp.h>

int main() {
    struct tcp_info info;
    printf("Sizeof tcp_info: %lu\n", sizeof(struct tcp_info));
    printf("Offset of tcpi_retransmits: %lu, size: %lu\n", offsetof(struct tcp_info, tcpi_retransmits), sizeof(info.tcpi_retransmits));
    printf("Offset of tcpi_lost: %lu, size: %lu\n", offsetof(struct tcp_info, tcpi_lost), sizeof(info.tcpi_lost));
    printf("Offset of tcpi_delivered: %lu, size: %lu\n", offsetof(struct tcp_info, tcpi_delivered), sizeof(info.tcpi_delivered));
    printf("Offset of tcpi_bytes_acked: %lu, size: %lu\n", offsetof(struct tcp_info, tcpi_bytes_acked), sizeof(info.tcpi_bytes_acked));
    printf("Offset of tcpi_total_retrans: %lu, size: %lu\n", offsetof(struct tcp_info, tcpi_total_retrans), sizeof(info.tcpi_total_retrans));
    printf("Offset of tcpi_rtt: %lu, size: %lu\n", offsetof(struct tcp_info, tcpi_rtt), sizeof(info.tcpi_rtt));
    printf("Offset of tcpi_snd_cwnd: %lu, size: %lu\n", offsetof(struct tcp_info, tcpi_snd_cwnd), sizeof(info.tcpi_snd_cwnd));
    printf("Offset of tcpi_rttvar: %lu, size: %lu\n", offsetof(struct tcp_info, tcpi_rttvar), sizeof(info.tcpi_rttvar));
    printf("Offset of tcpi_pacing_rate: %lu, size: %lu\n", offsetof(struct tcp_info, tcpi_pacing_rate), sizeof(info.tcpi_pacing_rate));
    printf("Offset of tcpi_bytes_sent: %lu, size: %lu\n", offsetof(struct tcp_info, tcpi_bytes_sent), sizeof(info.tcpi_bytes_sent));
}