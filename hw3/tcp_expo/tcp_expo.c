/*
 * TCP EXPO: The Momentum Engine
 *
 * OVERVIEW
 * --------
 * This is a custom Linux kernel TCP congestion control algorithm for CS536 Networks. 
 * The classic algorithms (Reno, CUBIC) react to *packet loss* as the primary
 * signal of congestion. We have designed EXPO instead watches RTT growth, the delay *
 * signal to detect and respond to congestion earlier, before the buffer overflows and
 * packets are dropped.
 *
 * WHAT IS HRC (High-RTT Congestion)?
 * ------------------------------------
 * HRC tells us that the condition where the Round-Trip Time (RTT) is inflated well
 * above the true propagation delay of the link, because intermediate router
 * buffers are filling up. This is also called "bufferbloat.", which we realized after 
 * testing through flent. The network is not
 * yet dropping packets, but it IS really congested; data is piling up in queues. This 
 * is one of the reasons we had to do the Negative Pulse, to try to fix this issue of 
 * queing delay. We went from 5000ms to almost 130ms of delay when we were doing the 
 * flent tests, which is really amazing, but getting the most throughput.
 * 
 * Classic loss-based algorithms (Reno/CUBIC) don't care of HRC. They keep
 * increasing CWND until a packet is dropped, which can take hundreds of
 * milliseconds of unnecessary delay. EXPO detects HRC early by monitoring
 * *momentum* (the ratio of RTT inflation to CWND size) and throttles growth
 * before the buffer completely fills.
 *
 * WHAT IS PSTM (Phase-Space Trajectory Mapping)?
 * -----------------------------------------------
 * We came up with help of AI idea of reating CWND as a single number to increment, it * treats the connection as a point moving through a 2D phase space defined by (CWND, 
 * RTT). The trajectory of this point reveals the "momentum" of the connection, 
 * whether it's accelerating smoothly, hitting friction from queuing delay, or 
 * spiraling into an HRC event.
 *
 * By watching how RTT changes proportionally to the delay, EXPO
 * classifies the connection's trajectory into three zones:
 *   - Clean zone (momentum < 512, <50% inflation) → RTT is stable. Accelerate.
 *   - Build zone (512-1024, 50-100% inflation) → queuing building. Grow cautiously.
 *   - Expo zone (momentum >= 1024, >100% inflation) → buffer saturating.
 *                     Apply a Negative Pulse (~1.5% CWND reduction) to probe relief.
 *
 * THREE PHASES
 * ------------------------
 * Phase 1 – Exponential Slow Start:
 *   CWND grows rapidly (doubling each RTT) until it reaches half of ssthresh.
 *   This quickly fills an empty pipe. We also start with window size 20 instead of 10 to be more 
 *   aggressive
 *
 * Phase 2 – PSTM Avoidance:
 *   Once past Phase 1, the algorithm enters PSTM-guided avoidance. Growth rate
 *   depends on real-time momentum measurement.
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <net/tcp.h>

/*
 * struct tcp_expo_data
 * --------------------
 *
 * clean_rtts:
 *   A counter of consecutive RTTs that passed without an expo event.
 *   Used as an acceleration multiplier — the longer the connection has been
 *   clean, the more aggressively EXPO accelerates CWND growth. Resets to 0
 *   whenever a Negative Pulse fires or ssthresh is recalculated (on loss).
 *
 * rtt_min:
 *   The lowest RTT ever observed on this connection.
 *   This represents the "baseline", the propagation delay of the
 *   link with empty buffers. It is used as the zero-point for momentum
 *   calculations. 
 *
 * rtt_min_tstamp:
 *   Timestamp of last rtt_min update or aging event.
 *   Used to pace the aging of rtt_min.
 *
 * momentum:
 *   Represents the RTT inflation.
 *   Computed as: (1024 * (srtt - rtt_min)) / rtt_min
 *   This is a RATIO.
 *   - momentum == 0    → no queuing delay at all (ideal)
 *   - momentum < 512   → <50% inflation → clean zone, aggressive growth
 *   - 512..1024         → 50-100% inflation → build zone, cautious growth
 *   - momentum >= 1024  → >100% inflation → expo event, Negative Pulse
 *
 * expo_event:
 *   Boolean flag (0 or 1). Set to 1 when momentum exceeds the critical
 *   threshold of 1024 (~100% RTT inflation). Triggers the Negative Pulse
 *   on the next call to tcp_expo_pstm_avoid(). Cleared after the pulse.
 *
 * last_pulse_tstamp:
 *   Timestamp of the last Negative Pulse firing.
 *   Used to enforce a cooldown of 3x the smoothed RTT between
 *   consecutive pulses. Without this, the pulse fires on every ACK
 *   while momentum stays high, collapsing CWND to the floor.
 */

struct tcp_expo_data {
    u32 clean_rtts;
    u32 rtt_min;
    u32 rtt_min_tstamp;
    s32 momentum;
    u8  expo_event;
    u32 last_pulse_tstamp;
};


/* =========================================================================
 * TRAJECTORY ANALYSIS
 * =========================================================================
 *
 * tcp_expo_update_trajectory() is called every time an ACK is processed.
 * It updates the connection's momentum reading and sets expo_event if
 * the trajectory has become unstable, high delay. This acts as a Panic Button that 
 * tells the rest of the code to trigger a Negative Pulse (dropping one packet) to save 
 * the connection from crashing.
 */

static void tcp_expo_update_trajectory(struct sock *sk)
{
    struct tcp_sock *tp = tcp_sk(sk);
    struct tcp_expo_data *ed = inet_csk_ca(sk);

    /*
     * srtt_us is the kernel's smoothed RTT estimate, stored as (RTT * 8)
     * in microseconds to avoid floating-point. Right-shifting by 3 (>> 3)
     * recovers the actual smoothed RTT in microseconds.
     *
     * When a new RTT sample comes in, the kernel only lets it change the "Average" by 
	 * a small percentage (usually 1/8th). (Used by CUBIC, BBR)
	 * It filters out the "noise".
     */
    u32 srtt = tp->srtt_us >> 3;

    /*
     * On the first ACK (rtt_min == 0) or whenever a new lower RTT is seen,
     * update rtt_min. This baseline drifts down over time if the path
     * becomes less congested.
     *
     * If no new minimum is seen for 10 seconds, we relax rtt_min toward current srtt by 1/16 of the 
     * gap. This prevents a one-time low RTT sample (for example, we saw that from an empty queue
     * at connection start) from permanently inflating the momentum reading.
     * Without aging, rtt_min at the lowest-ever sample and every
     * subsequent measurement looks like "high inflation", even when the
     * network is operating normally.
     * 
     * tcp_jiffies32: tell us roughly what time is it now
     */
    if (ed->rtt_min == 0 || srtt < ed->rtt_min) {
        ed->rtt_min = srtt;
        ed->rtt_min_tstamp = tcp_jiffies32;
    } else if (tcp_jiffies32 - ed->rtt_min_tstamp > msecs_to_jiffies(10000)) {
        /* Age rtt_min upward by 1/16 of the gap to current srtt */
        ed->rtt_min += (srtt - ed->rtt_min) >> 4;
        ed->rtt_min_tstamp = tcp_jiffies32;
    }

    /*
     * STEP 2: Compute RATIO-BASED momentum.
     *
     * formula: momentum = (1024 * (srtt - rtt_min)) / rtt_min
     * This is similar to what TCP Vegas do.
     *
     * How much the current RTT has grown as a fraction of the baseline 
     * propagation delay.
     *     momentum = 0     → no inflation
     *     momentum = 256   → 25% inflation (srtt is 1.25× rtt_min)
     *     momentum = 512   → 50% inflation (srtt is 1.5× rtt_min)
     *     momentum = 1024  → 100% inflation (RTT has doubled)
     * The momentum it is times srtt because 
     *
     * WHY scale by 1024?
     *   Linux kernel code avoids floating point. Scaling by 1024 befor 
     * the integer divide preserves ~10 bits of fractional precision.
     */
    if (ed->rtt_min > 0) {
        ed->momentum = (s32) ((1024UL * (srtt - ed->rtt_min)) / ed->rtt_min);
    }

    /*
     * STEP 3: Expo detection.
     *
     * If momentum >= 1024, the RTT has inflated by ~100% above baseline.
     * This means the RTT has doubled — significant queuing delay.
     *
     * why like this? Threshold:
     *   1024/1024 = 100% inflation. For a 10ms base-RTT link this triggers
     *   when srtt reaches ~20ms, meaning ~10ms of queuing delay.
     *   This tolerance lets CWND grow to fill the pipe before triggering,
     *   giving more throughput while still catching bufferbloat before it
     *   gets out of control.
     *
     * Setting expo_event = 1 signals tcp_expo_pstm_avoid() to fire
     * the Negative Pulse on the very next ACK-processing cycle.
     */
    if (ed->momentum >= 1024) {
        ed->expo_event = 1;
    }
}


/* =========================================================================
 * PHASE 2: PSTM AVOIDANCE
 * =========================================================================
 *
 * tcp_expo_pstm_avoid() is the heart of the algorithm. It is called once
 * the connection has exited slow start and entered the PSTM-guided
 * congestion avoidance phase.
 *
 * Parameters:
 *   sk    – the socket (connection) being managed
 *   acked – the number of newly acknowledged bytes in this ACK event
 */
static void tcp_expo_pstm_avoid(struct sock *sk, u32 acked)
{
    struct tcp_sock *tp = tcp_sk(sk);
    struct tcp_expo_data *ed = inet_csk_ca(sk);

    /*
     * The current CWND. We use this as the "window size" divisor
     * in the fractional increment logic below, so we want the value at
     * the start of this ACK event, not a value that may change mid-function.
     */
    u32 window_size = tp->snd_cwnd;

    /* Refresh the momentum and expo events (an expo event is when we go from smooth to chaotic traffic) readings. */
    tcp_expo_update_trajectory(sk);

    /*
     * -----------------------------------------------------------------------
     * NEGATIVE PULSE: Single-packet CWND reduction
     * -----------------------------------------------------------------------
     *
     * If an expo event event was flagged (momentum > 800), we do NOT halve CWND
     * like Reno/CUBIC would on a loss event. Instead, we subtract exactly 1
     * packet. This is a deliberate, try to test the network:
     *
     *   - One packet less in flight reduces the queue by a tiny amount. (This was our  	    
     *     deseparte attempt to fix our issue of queing delay while doing flent tests, and      
     *     professor advice)  
	 * 	   In order to see if its responsive or saturated.
	 * 
     *   - If the RTT drops on the next sample when removing one, the buffer was 
	 * 	   sensitive to that single packet, the network is near its saturation point, 	
	 * 	   here we will know that we can't continue growing and we need to be more careful is we 
     *     are going to start panicking. At this point
	 *
     *   - If RTT does not drop, the next trajectory update will detect it
     *     and fire another pulse. Because the RTT is still high, the next time the 	
	 * 	   code checks the "Trajectory," it will see that the Momentum is still over 
	 * 	   800. It will fire another Negative Pulse, dropping one more packet.
     *
     * The minimum CWND floor of 4 when the protocol breaks so badly it can't fix  	
	 * itself to near zero in the presence of sustained high latency.
     *
     * After the pulse:
     *   - expo_event is cleared so we don't fire twice.
     *   - clean_rtts is reset so the acceleration counter starts fresh.
     *   - We return immediately, skipping the normal growth logic for this
     *     ACK event (the CWND adjustment is already done).
     */
    if (ed->expo_event) {
        /*
         * COOLDOWN: Only fire the Negative Pulse once per 2× smoothed RTT.
         * Without this guard, the pulse fires on every single ACK while
         * momentum stays above the threshold (hundreds of times per RTT),
         * which collapses CWND to the floor almost instantly, we found out about this after seeing how our CWND was collapsing during the tests.
         *
         * Convert srtt from microseconds to jiffies for the comparison.
         * If not enough time has passed, clear the event flag and fall
         * through to the normal growth path below.
         */
        u32 srtt_jiffies = usecs_to_jiffies(tp->srtt_us >> 3);
        if (srtt_jiffies < 1)
            srtt_jiffies = 1;

        if (tcp_jiffies32 - ed->last_pulse_tstamp < (srtt_jiffies * 3)) {
            /* Cooldown active — suppress this pulse, allow gentle growth */
            ed->expo_event = 0;
        } else {
            /*
             * Fire the Negative Pulse: drop by ~1.5% (CWND / 64)
             *
             * Gentler than before (was CWND/32 ~3%). A 1.5% nudge is enough
             * to probe queue saturation while preserving window growth.
             * Combined with the 3× RTT cooldown, this gives more stable throughput.
             */
            u32 drop = max(tp->snd_cwnd >> 6, 1U);

            if (tp->snd_cwnd > 4 + drop)
                tp->snd_cwnd -= drop;
            else
                tp->snd_cwnd = 4;

            ed->expo_event = 0;
            ed->clean_rtts = 0;
            ed->last_pulse_tstamp = tcp_jiffies32;
            return;
        }
    }

    /*
     * -----------------------------------------------------------------------
     * ACCELERATION: Our Phase-aware CWND growth
     * -----------------------------------------------------------------------
     *
     * Growth rate is determined by the current momentum reading:
     *
     * THREE-ZONE GROWTH:
     *
     * CLEAN ZONE (momentum < 512, <50% RTT inflation):
     *   Packets are returning quickly, RTT is stable, buffers are not filling
     *   up. We grow aggressively. The acceleration factor starts at 2 and
     *   increases with clean_rtts — the longer the connection has been clean,
     *   the more confident EXPO is that the path can support faster growth.
     *
     *   Formula: accel = 2 + (clean_rtts >> 3)
     *     clean_rtts >> 3 means accel increases by 1 for every 8 clean RTTs.
     *     Cap: accel = min(accel, 8)
     *
     *
     * BUILD ZONE (512 <= momentum < 1024, 50-100% inflation):
     *   Some queuing delay is present but not critical. We grow at a moderate
     *   rate — faster than Reno (1 pkt/RTT) but slower than the clean zone.
     *   This keeps probing for capacity without overfilling the buffer.
     *
     *   Formula: accel = 1 + (clean_rtts >> 4), cap at 4
     *
     * HIGH ZONE (momentum >= 1024, between Negative Pulse cooldowns):
     *   During the cooldown period after a pulse is suppressed, we still
     *   allow Reno rate growth (accel = 1). This prevents the connection
     *   from stalling while waiting for the next pulse opportunity.
     */
    u32 accel;
    if (ed->momentum < 512) {
        /* Clean zone: aggressive growth */
        accel = 2 + (ed->clean_rtts >> 3);
        if (accel > 8) accel = 8;
    } else if (ed->momentum < 1024) {
        /*
         * Build zone: moderate growth.
         * Faster than Reno, slower than clean zone. Lets us probe for
         * the capacity ceiling without triggering a full HRC event.
         */
        accel = 1 + (ed->clean_rtts >> 4);
        if (accel > 4) accel = 4;
    } else {
        /*
         * High zone (between pulses during cooldown): Reno rate growth.
         * The Negative Pulse mechanism handles the backing-off; between
         * pulses we still need gentle growth to avoid stalling.
         */
        accel = 1;
    }

    /*
     * FRACTIONAL INCREMENT (low-momentum path only):
     *
     * snd_cwnd_cnt accumulates (acked * accel) on each ACK. Once it exceeds
     * window_size, we have logically received enough acknowledgement to
     * justify increasing CWND. The integer division delta = cnt / window_size
     * allows multi-packet increments when accel is high (accel=8 means
     * we can increment CWND by up to 8 in a single burst of ACKs). The
     * remainder is kept in snd_cwnd_cnt so fractional progress is not lost.
     *
     * When accel == 0 (high-momentum branch above already returned), this
     * block is still reached but adds nothing, since accel=0 means
     * snd_cwnd_cnt += acked * 0 == no change.
     */
    tp->snd_cwnd_cnt += acked * accel;

    if (tp->snd_cwnd_cnt >= window_size) {
        u32 delta = tp->snd_cwnd_cnt / window_size;
        tp->snd_cwnd_cnt -= delta * window_size;
        tp->snd_cwnd += delta;
        /*
         * Increment clean_rtts only when CWND actually grows. This ensures
         * the acceleration counter reflects "cleans" RTTs, not idle ones.
         */
        ed->clean_rtts++;
    }

    /*
     * Hard clamp: never exceed snd_cwnd_clamp, the kernel-enforced absolute
     * maximum (set by the receive window advertised by the remote host, or
     * by sysctl tcp_max_ssthresh). (This comes from the reno code)
     */
    tp->snd_cwnd = min(tp->snd_cwnd, tp->snd_cwnd_clamp);
}


/* =========================================================================
 * LOSS RESPONSE: tcp_expo_ssthresh
 * =========================================================================
 *
 * Called when the kernel detects a loss event (timeout or 3 duplicate ACKs).
 * Must return the new slow-start threshold (ssthresh), the CWND value at
 * which the connection should switch from exponential slow-start back into
 * congestion avoidance after the recovery.
 *
 * This implementation is bit more aggressive than normal Reno (which
 * uses CWND/2). We cut by 12.5% (1/8) instead of 50%, keeping more CWND
 * intact after loss. We thought that EXPO's trajectory monitoring should have
 * already backed off via Negative Pulses before a true loss occurs, so when
 * a loss does happen it is likely a temporary event.
 *
 * Formula: ssthresh = max(snd_cwnd - snd_cwnd/8, 2)
 *
 * clean_rtts is reset here so that acceleration rebuilds from scratch after
 * the recovery period, just as it does after a Negative Pulse.
 */
static u32 tcp_expo_ssthresh(struct sock *sk)
{
    const struct tcp_sock *tp = tcp_sk(sk);
    struct tcp_expo_data *ed = inet_csk_ca(sk);
    ed->clean_rtts = 0;

    return max(tp->snd_cwnd - (tp->snd_cwnd >> 3U), 2U);
}


/* =========================================================================
 * MAIN CONGESTION AVOIDANCE ENTRY POINT: tcp_expo_cong_avoid
 * =========================================================================
 *
 * This is the function registered with the kernel and called on every
 * incoming ACK. 
 *
 * Parameters:
 *   sk    – the socket
 *   ack   – the ACK number received (unused here, passed for API compatibility)
 *   acked – the number of bytes newly acknowledged by this ACK
 */
void tcp_expo_cong_avoid(struct sock *sk, u32 ack, u32 acked)
{
    struct tcp_sock *tp = tcp_sk(sk);

    /*
     * is_cwnd_limited: kernel flag that is true only when the sender is
     * actually constrained by CWND (there is more data to send than
     * CWND allows). If the application is not sending enough to fill the
     * window, growing CWND has no effect and we should not inflate it
     * artificially.
     */
    if (!tp->is_cwnd_limited) return;

    /*
     * PHASE 1 — Exponential Slow Start
     * ----------------------------------
     * During slow start, CWND grows by the number of newly ACKed bytes
     * each RTT, doubling each RTT. This rapidly fills an
     * empty pipe without waiting for multiple RTTs.
     *
     * We use ssthresh as the Phase 1 ceiling (standard TCP behavior).
     * Once CWND reaches ssthresh, we fall through to Phase 2 where
     * PSTM avoidance takes over with momentum-guided growth.
     */
    if (tp->snd_cwnd < tp->snd_ssthresh) {
        tp->snd_cwnd = min(tp->snd_cwnd + acked, tp->snd_ssthresh);
        return;
    }

    /*
     * PHASE 2 — PSTM Avoidance
     * -------------------------
     * Full trajectory congestion avoidance. See tcp_expo_pstm_avoid()
     * above for the complete description of momentum-based growth and the
     * Negative Pulse mechanism.
     */
    tcp_expo_pstm_avoid(sk, acked);
}


/* =========================================================================
 * CONNECTION INITIALIZATION: tcp_expo_init
 * =========================================================================
 *
 * Called when a new TCP connection begins using this congestion algorithm.
 * Resets all per-connection EXPO state to clean initial values.
 *
 * snd_cwnd is set to 20 segments as the initial window. The standard Linux
 * default is 10. Using 20 here gives us faster ramp-up on high-BDP
 * links. The Phase-Space Trajectory Mapping monitoring will quickly detect
 * if 20 is too aggressive and apply a Negative Pulse to correct it.
 */
static void tcp_expo_init(struct sock *sk)
{
    struct tcp_sock *tp = tcp_sk(sk);
    struct tcp_expo_data *ed = inet_csk_ca(sk);
    tp->snd_cwnd = 20;
    ed->clean_rtts = 0;
    ed->rtt_min = 0;          /* Will be set on the first ACK */
    ed->rtt_min_tstamp = 0;   /* Will be set with rtt_min */
    ed->momentum = 0;
    ed->expo_event = 0;
    ed->last_pulse_tstamp = 0;
}

/* =========================================================================
 * LOSS RECOVERY: tcp_expo_undo_cwnd
 * =========================================================================
 *
 * Called when the kernel decides to undo a CWND reduction (e.g. after a
 * false positive loss event). Must return the CWND value to restore.
 *
 * Since the loss was a false positive, we clear expo_event so a spurious
 * Negative Pulse does not fire on the next ACK, and let the acceleration
 * counter (clean_rtts) remain at whatever value ssthresh set it to (0),
 * so growth ramps back up naturally through PSTM avoidance.
 */
static u32 tcp_expo_undo_cwnd(struct sock *sk)
{
    const struct tcp_sock *tp = tcp_sk(sk);
    struct tcp_expo_data *ed = inet_csk_ca(sk);
    ed->expo_event = 0;

    return max(tp->snd_cwnd, tp->prior_cwnd);
}

/* =========================================================================
 * KERNEL REGISTRATION
 * =========================================================================
 *
 * tcp_expo is the ops struct that tells the kernel how to call into this
 * module. The .name field is the string used to activate this algorithm
 * (e.g. "sysctl -w net.ipv4.tcp_congestion_control=expo").
 *
 */

static struct tcp_congestion_ops tcp_expo = {
    .flags		= TCP_CONG_NON_RESTRICTED,
    .name       = "expo",
    .init       = tcp_expo_init,
    .owner      = THIS_MODULE,
    .ssthresh   = tcp_expo_ssthresh,
    .cong_avoid = tcp_expo_cong_avoid,
    .undo_cwnd	= tcp_expo_undo_cwnd,
};

static int __init tcp_expo_register(void)
{
    return tcp_register_congestion_control(&tcp_expo);
}

static void __exit tcp_expo_unregister(void)
{
    tcp_unregister_congestion_control(&tcp_expo);
}

module_init(tcp_expo_register);
module_exit(tcp_expo_unregister);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("TCP EXPO: The Momentum Engine");