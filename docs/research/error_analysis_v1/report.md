# Phase 13A — error_analysis v1

## Identity and lineage

- study: `error_analysis_v1` (schema 1); fingerprint `9081b83bc75ffff8f14d4c3f1f42463d0a15efa6bb93216fe7daa9f737e64e1c`
- git commit: `9ce8dab743bde6ace5737ab8e815f430d3b60c76`; generated at: `2026-09-18T22:01:15.455870+00:00`
- source: `baseline_study` v1, fingerprint `1bd69ea2e4b11e8858868f8f4d353ca5442f285b2a43fdb09c28f6569ae00261`, methodology `5cc0ba19775f4a8dcb40bb1ceae69a17cc388f31`, result `3625e10656b6d11b40479a09d2c467e190480b2e`
- source artifacts verified by SHA-256: `manifest.json` `d6d4d8e7f612558b68b80da5c4b4a545916d2d6bf3a8e60de9eb7cef3a6158bf`, `summary.csv` `cbae399af9afd181aa02eb1d2e8a420e2be63283abe3ce60631f1662ebcd49ee`, `observations.csv` `c2be1f66f10d7dc31debfaac76d67c850664166a65d1585bdd3769d0a228af76`
- source rows: 37740; Phase R result rows recomputed and matched: 255
- observation window `[2015-01-01T00:00:00+00:00, 2025-01-01T00:00:00+00:00)`; no later row accepted; data from 2025-03-01 onward not read
- network: none

## D6 — Semantic contract

- The source vocabulary (src/strategies/research.py) defines BULLISH as "this deterministic hypothesis classifies the supplied evidence as bullish-leaning" and states that it does not mean "buy" or "this will rise"; BEARISH is the mirror. The states are structural classifications of the current SMA20/SMA50 configuration (and, for momentum_in_trend_context, RSI14 read against it); they promise nothing about forward direction.
- Accordingly, the Phase R observation on the equity ETFs is described here as: observed state-conditioned forward-return differences opposite to the colloquial directional connotation of the state names. It is not described as a wrong prediction, and this analysis does not reverse, rename or re-tune any state.

## D1 — Episode structure

| hypothesis | symbol | class | state | observations | episodes | len min | len median | len max | share largest | share top 3 |
|---|---|---|---|---|---|---|---|---|---|---|
| trend_alignment | SPY | equity | bullish | 1709 | 26 | 3 | 54.500000 | 237 | 0.138678 | 0.269163 |
| trend_alignment | SPY | equity | bearish | 724 | 23 | 2 | 22.000000 | 72 | 0.099448 | 0.266575 |
| trend_alignment | SPY | equity | neutral | 83 | 39 | 1 | 1.000000 | 9 | 0.108434 | 0.277108 |
| momentum_in_trend_context | SPY | equity | bullish | 1189 | 103 | 1 | 7.000000 | 60 | 0.050463 | 0.133726 |
| momentum_in_trend_context | SPY | equity | bearish | 279 | 63 | 1 | 2.000000 | 18 | 0.064516 | 0.189964 |
| momentum_in_trend_context | SPY | equity | neutral | 1048 | 167 | 1 | 3.000000 | 36 | 0.034351 | 0.099237 |
| trend_crossover | SPY | equity | bullish | 25 | 25 | 1 | 1.000000 | 1 | 0.040000 | 0.120000 |
| trend_crossover | SPY | equity | bearish | 25 | 25 | 1 | 1.000000 | 1 | 0.040000 | 0.120000 |
| trend_crossover | SPY | equity | neutral | 2466 | 50 | 1 | 39.500000 | 236 | 0.095702 | 0.187753 |
| trend_alignment | QQQ | equity | bullish | 1732 | 27 | 3 | 45.000000 | 151 | 0.087182 | 0.250000 |
| trend_alignment | QQQ | equity | bearish | 722 | 25 | 4 | 23.000000 | 73 | 0.101108 | 0.268698 |
| trend_alignment | QQQ | equity | neutral | 62 | 41 | 1 | 1.000000 | 5 | 0.080645 | 0.209677 |
| momentum_in_trend_context | QQQ | equity | bullish | 1187 | 115 | 1 | 6.000000 | 60 | 0.050548 | 0.128054 |
| momentum_in_trend_context | QQQ | equity | bearish | 288 | 52 | 1 | 4.000000 | 27 | 0.093750 | 0.208333 |
| momentum_in_trend_context | QQQ | equity | neutral | 1041 | 168 | 1 | 3.500000 | 37 | 0.035543 | 0.097022 |
| trend_crossover | QQQ | equity | bullish | 25 | 25 | 1 | 1.000000 | 1 | 0.040000 | 0.120000 |
| trend_crossover | QQQ | equity | bearish | 25 | 25 | 1 | 1.000000 | 1 | 0.040000 | 0.120000 |
| trend_crossover | QQQ | equity | neutral | 2466 | 51 | 4 | 33.000000 | 174 | 0.070560 | 0.184915 |
| trend_alignment | IWM | equity | bullish | 1580 | 32 | 11 | 33.000000 | 153 | 0.096835 | 0.237342 |
| trend_alignment | IWM | equity | bearish | 850 | 27 | 2 | 23.000000 | 78 | 0.091765 | 0.256471 |
| trend_alignment | IWM | equity | neutral | 86 | 51 | 1 | 1.000000 | 8 | 0.093023 | 0.220930 |
| momentum_in_trend_context | IWM | equity | bullish | 874 | 130 | 1 | 3.000000 | 59 | 0.067506 | 0.172769 |
| momentum_in_trend_context | IWM | equity | bearish | 382 | 71 | 1 | 2.000000 | 32 | 0.083770 | 0.196335 |
| momentum_in_trend_context | IWM | equity | neutral | 1260 | 201 | 1 | 4.000000 | 36 | 0.028571 | 0.077778 |
| trend_crossover | IWM | equity | bullish | 29 | 29 | 1 | 1.000000 | 1 | 0.034483 | 0.103448 |
| trend_crossover | IWM | equity | bearish | 30 | 30 | 1 | 1.000000 | 1 | 0.033333 | 0.100000 |
| trend_crossover | IWM | equity | neutral | 2457 | 59 | 1 | 29.000000 | 155 | 0.063085 | 0.158323 |
| trend_alignment | TLT | treasury | bullish | 1161 | 27 | 1 | 34.000000 | 135 | 0.116279 | 0.265289 |
| trend_alignment | TLT | treasury | bearish | 1243 | 29 | 1 | 29.000000 | 166 | 0.133548 | 0.351569 |
| trend_alignment | TLT | treasury | neutral | 112 | 52 | 1 | 1.000000 | 12 | 0.107143 | 0.267857 |
| momentum_in_trend_context | TLT | treasury | bullish | 599 | 85 | 1 | 3.000000 | 44 | 0.073456 | 0.175292 |
| momentum_in_trend_context | TLT | treasury | bearish | 696 | 85 | 1 | 4.000000 | 60 | 0.086207 | 0.222701 |
| momentum_in_trend_context | TLT | treasury | neutral | 1221 | 169 | 1 | 4.000000 | 35 | 0.028665 | 0.073710 |
| trend_crossover | TLT | treasury | bullish | 28 | 28 | 1 | 1.000000 | 1 | 0.035714 | 0.107143 |
| trend_crossover | TLT | treasury | bearish | 29 | 29 | 1 | 1.000000 | 1 | 0.034483 | 0.103448 |
| trend_crossover | TLT | treasury | neutral | 2459 | 57 | 1 | 32.000000 | 166 | 0.067507 | 0.178121 |
| trend_alignment | GLD | gold | bullish | 1325 | 27 | 2 | 46.000000 | 114 | 0.086038 | 0.237736 |
| trend_alignment | GLD | gold | bearish | 1099 | 28 | 7 | 34.500000 | 108 | 0.098271 | 0.259327 |
| trend_alignment | GLD | gold | neutral | 92 | 48 | 1 | 1.000000 | 10 | 0.108696 | 0.282609 |
| momentum_in_trend_context | GLD | gold | bullish | 787 | 91 | 1 | 3.000000 | 38 | 0.048285 | 0.141042 |
| momentum_in_trend_context | GLD | gold | bearish | 496 | 90 | 1 | 3.000000 | 49 | 0.098790 | 0.223790 |
| momentum_in_trend_context | GLD | gold | neutral | 1233 | 182 | 1 | 4.000000 | 27 | 0.021898 | 0.064882 |
| trend_crossover | GLD | gold | bullish | 27 | 27 | 1 | 1.000000 | 1 | 0.037037 | 0.111111 |
| trend_crossover | GLD | gold | bearish | 28 | 28 | 1 | 1.000000 | 1 | 0.035714 | 0.107143 |
| trend_crossover | GLD | gold | neutral | 2461 | 56 | 2 | 41.500000 | 113 | 0.045916 | 0.133685 |

### Episode-start sampling view (secondary; not a replacement, not an independence correction)

| hypothesis | symbol | state | h | episodes | n | mean | median | min | max | pos | neg | zero |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| trend_alignment | SPY | bullish | 1 | 26 | 26 | -0.000202 | +0.000115 | -0.012000 | +0.013795 | 14 | 12 | 0 |
| trend_alignment | SPY | bullish | 5 | 26 | 26 | -0.000114 | +0.001167 | -0.047527 | +0.024629 | 16 | 10 | 0 |
| trend_alignment | SPY | bullish | 20 | 26 | 26 | +0.005634 | +0.012505 | -0.085321 | +0.066629 | 16 | 10 | 0 |
| trend_alignment | SPY | bearish | 1 | 23 | 23 | +0.000259 | +0.000036 | -0.019333 | +0.024016 | 12 | 11 | 0 |
| trend_alignment | SPY | bearish | 5 | 23 | 23 | -0.003287 | +0.006154 | -0.100400 | +0.037626 | 13 | 10 | 0 |
| trend_alignment | SPY | bearish | 20 | 23 | 23 | -0.006090 | -0.002474 | -0.192898 | +0.072081 | 11 | 12 | 0 |
| trend_alignment | SPY | neutral | 1 | 39 | 39 | +0.003241 | +0.001436 | -0.012945 | +0.022017 | 27 | 12 | 0 |
| trend_alignment | SPY | neutral | 5 | 39 | 39 | +0.004410 | +0.006554 | -0.057820 | +0.033740 | 26 | 13 | 0 |
| trend_alignment | SPY | neutral | 20 | 39 | 39 | +0.003150 | +0.010343 | -0.158010 | +0.063437 | 23 | 16 | 0 |
| momentum_in_trend_context | SPY | bullish | 1 | 103 | 103 | -0.000769 | -0.000375 | -0.033573 | +0.014081 | 48 | 54 | 1 |
| momentum_in_trend_context | SPY | bullish | 5 | 103 | 103 | +0.001429 | +0.004112 | -0.054770 | +0.030325 | 65 | 38 | 0 |
| momentum_in_trend_context | SPY | bullish | 20 | 103 | 103 | +0.010517 | +0.013351 | -0.122654 | +0.097049 | 72 | 31 | 0 |
| momentum_in_trend_context | SPY | bearish | 1 | 63 | 63 | +0.001770 | +0.001373 | -0.028085 | +0.027081 | 37 | 26 | 0 |
| momentum_in_trend_context | SPY | bearish | 5 | 63 | 63 | +0.001283 | +0.005299 | -0.071490 | +0.117623 | 36 | 27 | 0 |
| momentum_in_trend_context | SPY | bearish | 20 | 63 | 63 | +0.019853 | +0.025180 | -0.158010 | +0.184714 | 43 | 20 | 0 |
| momentum_in_trend_context | SPY | neutral | 1 | 167 | 167 | -0.000379 | +0.000583 | -0.034814 | +0.018598 | 98 | 68 | 1 |
| momentum_in_trend_context | SPY | neutral | 5 | 167 | 167 | +0.001619 | +0.004511 | -0.083184 | +0.045826 | 95 | 72 | 0 |
| momentum_in_trend_context | SPY | neutral | 20 | 167 | 167 | +0.013745 | +0.018100 | -0.291948 | +0.117266 | 119 | 48 | 0 |
| trend_crossover | SPY | bullish | 1 | 25 | 25 | +0.000885 | +0.001254 | -0.009225 | +0.013337 | 15 | 10 | 0 |
| trend_crossover | SPY | bullish | 5 | 25 | 25 | +0.000651 | +0.002559 | -0.047527 | +0.021689 | 16 | 9 | 0 |
| trend_crossover | SPY | bullish | 20 | 25 | 25 | +0.006408 | +0.011076 | -0.085321 | +0.066629 | 16 | 9 | 0 |
| trend_crossover | SPY | bearish | 1 | 25 | 25 | +0.002983 | +0.001809 | -0.016655 | +0.022017 | 16 | 9 | 0 |
| trend_crossover | SPY | bearish | 5 | 25 | 25 | -0.003864 | +0.006349 | -0.104357 | +0.037626 | 14 | 11 | 0 |
| trend_crossover | SPY | bearish | 20 | 25 | 25 | -0.005139 | -0.004118 | -0.158010 | +0.072081 | 11 | 14 | 0 |
| trend_crossover | SPY | neutral | 1 | 50 | 50 | -0.000252 | -0.000655 | -0.016018 | +0.028724 | 21 | 29 | 0 |
| trend_crossover | SPY | neutral | 5 | 50 | 50 | -0.002739 | +0.000432 | -0.100400 | +0.043559 | 27 | 23 | 0 |
| trend_crossover | SPY | neutral | 20 | 50 | 50 | -0.000622 | +0.003529 | -0.192898 | +0.091847 | 27 | 23 | 0 |
| trend_alignment | QQQ | bullish | 1 | 27 | 27 | +0.001282 | +0.001616 | -0.026781 | +0.015795 | 16 | 11 | 0 |
| trend_alignment | QQQ | bullish | 5 | 27 | 27 | +0.001579 | +0.001268 | -0.045550 | +0.041780 | 16 | 11 | 0 |
| trend_alignment | QQQ | bullish | 20 | 27 | 27 | +0.005618 | +0.018156 | -0.119242 | +0.060446 | 17 | 10 | 0 |
| trend_alignment | QQQ | bearish | 1 | 25 | 25 | +0.000685 | +0.005386 | -0.032283 | +0.020503 | 15 | 10 | 0 |
| trend_alignment | QQQ | bearish | 5 | 25 | 25 | +0.000338 | +0.004430 | -0.086331 | +0.043969 | 15 | 10 | 0 |
| trend_alignment | QQQ | bearish | 20 | 25 | 25 | +0.018492 | +0.028534 | -0.077434 | +0.101092 | 17 | 8 | 0 |
| trend_alignment | QQQ | neutral | 1 | 41 | 41 | -0.001524 | -0.000084 | -0.038993 | +0.022112 | 20 | 21 | 0 |
| trend_alignment | QQQ | neutral | 5 | 41 | 41 | +0.001935 | +0.002228 | -0.073190 | +0.052546 | 22 | 19 | 0 |
| trend_alignment | QQQ | neutral | 20 | 41 | 41 | +0.010123 | +0.016964 | -0.133194 | +0.095332 | 28 | 13 | 0 |
| momentum_in_trend_context | QQQ | bullish | 1 | 115 | 115 | +0.000979 | +0.000597 | -0.026781 | +0.027147 | 65 | 50 | 0 |
| momentum_in_trend_context | QQQ | bullish | 5 | 115 | 115 | +0.003628 | +0.007573 | -0.064260 | +0.057009 | 69 | 46 | 0 |
| momentum_in_trend_context | QQQ | bullish | 20 | 115 | 115 | +0.008641 | +0.013376 | -0.146612 | +0.132769 | 71 | 44 | 0 |
| momentum_in_trend_context | QQQ | bearish | 1 | 52 | 52 | -0.000692 | -0.001929 | -0.032283 | +0.031499 | 23 | 29 | 0 |
| momentum_in_trend_context | QQQ | bearish | 5 | 52 | 52 | -0.003935 | +0.000446 | -0.086331 | +0.106654 | 26 | 25 | 1 |
| momentum_in_trend_context | QQQ | bearish | 20 | 52 | 52 | +0.028640 | +0.030652 | -0.106811 | +0.207846 | 37 | 15 | 0 |
| momentum_in_trend_context | QQQ | neutral | 1 | 168 | 168 | +0.000035 | +0.001066 | -0.037427 | +0.023671 | 91 | 76 | 1 |
| momentum_in_trend_context | QQQ | neutral | 5 | 168 | 168 | +0.004871 | +0.007517 | -0.102500 | +0.082511 | 113 | 55 | 0 |
| momentum_in_trend_context | QQQ | neutral | 20 | 168 | 168 | +0.016313 | +0.016887 | -0.236461 | +0.146537 | 112 | 55 | 1 |
| trend_crossover | QQQ | bullish | 1 | 25 | 25 | +0.001257 | +0.001065 | -0.026781 | +0.022112 | 15 | 10 | 0 |
| trend_crossover | QQQ | bullish | 5 | 25 | 25 | +0.003304 | +0.005295 | -0.045550 | +0.052546 | 16 | 9 | 0 |
| trend_crossover | QQQ | bullish | 20 | 25 | 25 | +0.009954 | +0.023659 | -0.119242 | +0.060446 | 17 | 8 | 0 |
| trend_crossover | QQQ | bearish | 1 | 25 | 25 | -0.003237 | -0.002368 | -0.032283 | +0.020503 | 10 | 15 | 0 |
| trend_crossover | QQQ | bearish | 5 | 25 | 25 | -0.003084 | +0.000891 | -0.086331 | +0.037545 | 13 | 12 | 0 |
| trend_crossover | QQQ | bearish | 20 | 25 | 25 | +0.015268 | +0.028534 | -0.106811 | +0.101092 | 17 | 8 | 0 |
| trend_crossover | QQQ | neutral | 1 | 51 | 51 | +0.002188 | +0.003199 | -0.026196 | +0.018389 | 33 | 18 | 0 |
| trend_crossover | QQQ | neutral | 5 | 51 | 51 | +0.001061 | +0.001268 | -0.049703 | +0.049132 | 26 | 25 | 0 |
| trend_crossover | QQQ | neutral | 20 | 51 | 51 | +0.013736 | +0.020731 | -0.111401 | +0.101488 | 33 | 18 | 0 |
| trend_alignment | IWM | bullish | 1 | 32 | 32 | +0.002025 | +0.000890 | -0.021914 | +0.030068 | 19 | 13 | 0 |
| trend_alignment | IWM | bullish | 5 | 32 | 32 | +0.003028 | +0.003177 | -0.044240 | +0.048712 | 18 | 14 | 0 |
| trend_alignment | IWM | bullish | 20 | 32 | 32 | +0.012868 | +0.003581 | -0.097404 | +0.140741 | 20 | 12 | 0 |
| trend_alignment | IWM | bearish | 1 | 27 | 27 | +0.000724 | -0.000254 | -0.016237 | +0.026302 | 13 | 14 | 0 |
| trend_alignment | IWM | bearish | 5 | 27 | 27 | -0.003345 | +0.002231 | -0.081669 | +0.030195 | 17 | 10 | 0 |
| trend_alignment | IWM | bearish | 20 | 27 | 27 | +0.005139 | +0.026243 | -0.305699 | +0.099077 | 17 | 10 | 0 |
| trend_alignment | IWM | neutral | 1 | 51 | 51 | -0.002118 | -0.002291 | -0.023814 | +0.020706 | 22 | 29 | 0 |
| trend_alignment | IWM | neutral | 5 | 51 | 51 | +0.000987 | +0.005725 | -0.095947 | +0.060931 | 30 | 21 | 0 |
| trend_alignment | IWM | neutral | 20 | 51 | 51 | +0.006842 | +0.019741 | -0.373533 | +0.143097 | 31 | 20 | 0 |
| momentum_in_trend_context | IWM | bullish | 1 | 130 | 130 | -0.001303 | -0.000057 | -0.032559 | +0.017837 | 64 | 66 | 0 |
| momentum_in_trend_context | IWM | bullish | 5 | 130 | 130 | -0.000435 | -0.000053 | -0.080288 | +0.094770 | 65 | 65 | 0 |
| momentum_in_trend_context | IWM | bullish | 20 | 130 | 130 | -0.002829 | +0.004550 | -0.250804 | +0.173913 | 72 | 57 | 1 |
| momentum_in_trend_context | IWM | bearish | 1 | 71 | 71 | +0.000743 | +0.000309 | -0.038211 | +0.026302 | 36 | 35 | 0 |
| momentum_in_trend_context | IWM | bearish | 5 | 71 | 71 | +0.001228 | +0.006953 | -0.085154 | +0.075943 | 40 | 31 | 0 |
| momentum_in_trend_context | IWM | bearish | 20 | 71 | 71 | +0.013370 | +0.026461 | -0.385306 | +0.159711 | 49 | 22 | 0 |
| momentum_in_trend_context | IWM | neutral | 1 | 201 | 201 | +0.000313 | +0.001081 | -0.034329 | +0.024166 | 110 | 91 | 0 |
| momentum_in_trend_context | IWM | neutral | 5 | 201 | 201 | -0.000735 | +0.001053 | -0.109278 | +0.091716 | 105 | 96 | 0 |
| momentum_in_trend_context | IWM | neutral | 20 | 201 | 201 | +0.003351 | +0.007111 | -0.373533 | +0.163390 | 118 | 83 | 0 |
| trend_crossover | IWM | bullish | 1 | 29 | 29 | +0.000752 | +0.001208 | -0.017531 | +0.019412 | 16 | 13 | 0 |
| trend_crossover | IWM | bullish | 5 | 29 | 29 | +0.005555 | +0.010059 | -0.045301 | +0.055006 | 18 | 11 | 0 |
| trend_crossover | IWM | bullish | 20 | 29 | 29 | +0.013204 | -0.002500 | -0.097404 | +0.143097 | 14 | 15 | 0 |
| trend_crossover | IWM | bearish | 1 | 30 | 30 | +0.000261 | +0.000184 | -0.038211 | +0.026302 | 16 | 14 | 0 |
| trend_crossover | IWM | bearish | 5 | 30 | 30 | -0.002922 | +0.004640 | -0.081669 | +0.060931 | 18 | 12 | 0 |
| trend_crossover | IWM | bearish | 20 | 30 | 30 | +0.005044 | +0.025347 | -0.385306 | +0.130298 | 19 | 11 | 0 |
| trend_crossover | IWM | neutral | 1 | 59 | 59 | -0.000890 | -0.001864 | -0.022468 | +0.030068 | 24 | 35 | 0 |
| trend_crossover | IWM | neutral | 5 | 59 | 59 | -0.000837 | +0.002231 | -0.081619 | +0.048712 | 33 | 26 | 0 |
| trend_crossover | IWM | neutral | 20 | 59 | 59 | +0.008274 | +0.008343 | -0.305699 | +0.153811 | 36 | 23 | 0 |
| trend_alignment | TLT | bullish | 1 | 27 | 27 | +0.000038 | -0.001024 | -0.011003 | +0.011074 | 12 | 15 | 0 |
| trend_alignment | TLT | bullish | 5 | 27 | 27 | +0.002365 | +0.002207 | -0.020367 | +0.029790 | 17 | 10 | 0 |
| trend_alignment | TLT | bullish | 20 | 27 | 27 | +0.000729 | -0.003594 | -0.078780 | +0.090587 | 12 | 15 | 0 |
| trend_alignment | TLT | bearish | 1 | 29 | 29 | -0.000032 | +0.000540 | -0.010091 | +0.012982 | 15 | 14 | 0 |
| trend_alignment | TLT | bearish | 5 | 29 | 29 | -0.003829 | +0.000422 | -0.033680 | +0.022959 | 15 | 14 | 0 |
| trend_alignment | TLT | bearish | 20 | 29 | 29 | +0.001884 | +0.008401 | -0.074186 | +0.053499 | 16 | 13 | 0 |
| trend_alignment | TLT | neutral | 1 | 52 | 52 | +0.001214 | +0.001630 | -0.011610 | +0.016999 | 30 | 21 | 1 |
| trend_alignment | TLT | neutral | 5 | 52 | 52 | +0.000840 | -0.000645 | -0.045551 | +0.036752 | 25 | 27 | 0 |
| trend_alignment | TLT | neutral | 20 | 52 | 52 | +0.000057 | +0.003865 | -0.103623 | +0.098002 | 29 | 23 | 0 |
| momentum_in_trend_context | TLT | bullish | 1 | 85 | 85 | +0.000872 | +0.001060 | -0.064343 | +0.053968 | 48 | 36 | 1 |
| momentum_in_trend_context | TLT | bullish | 5 | 85 | 85 | +0.000814 | +0.000082 | -0.030621 | +0.064762 | 44 | 40 | 1 |
| momentum_in_trend_context | TLT | bullish | 20 | 85 | 85 | +0.000807 | -0.001428 | -0.071407 | +0.156358 | 41 | 44 | 0 |
| momentum_in_trend_context | TLT | bearish | 1 | 85 | 85 | +0.000121 | +0.000960 | -0.017360 | +0.011797 | 46 | 39 | 0 |
| momentum_in_trend_context | TLT | bearish | 5 | 85 | 85 | -0.002221 | -0.002148 | -0.058275 | +0.043071 | 41 | 44 | 0 |
| momentum_in_trend_context | TLT | bearish | 20 | 85 | 85 | -0.004071 | +0.002072 | -0.097813 | +0.077563 | 44 | 41 | 0 |
| momentum_in_trend_context | TLT | neutral | 1 | 169 | 169 | -0.000203 | +0.000073 | -0.055548 | +0.022010 | 85 | 82 | 2 |
| momentum_in_trend_context | TLT | neutral | 5 | 169 | 169 | -0.000583 | -0.001576 | -0.042035 | +0.065886 | 78 | 91 | 0 |
| momentum_in_trend_context | TLT | neutral | 20 | 169 | 169 | -0.003003 | +0.001708 | -0.082009 | +0.114925 | 90 | 79 | 0 |
| trend_crossover | TLT | bullish | 1 | 28 | 28 | +0.000466 | -0.000423 | -0.011610 | +0.011074 | 13 | 14 | 1 |
| trend_crossover | TLT | bullish | 5 | 28 | 28 | +0.004385 | +0.004716 | -0.020960 | +0.032786 | 20 | 8 | 0 |
| trend_crossover | TLT | bullish | 20 | 28 | 28 | -0.000862 | -0.000298 | -0.078780 | +0.090587 | 14 | 14 | 0 |
| trend_crossover | TLT | bearish | 1 | 29 | 29 | +0.001062 | +0.002105 | -0.007188 | +0.008328 | 16 | 13 | 0 |
| trend_crossover | TLT | bearish | 5 | 29 | 29 | -0.002334 | +0.002185 | -0.033680 | +0.026532 | 16 | 13 | 0 |
| trend_crossover | TLT | bearish | 20 | 29 | 29 | +0.001271 | +0.003867 | -0.074186 | +0.049840 | 18 | 11 | 0 |
| trend_crossover | TLT | neutral | 1 | 57 | 57 | +0.000083 | +0.000406 | -0.011722 | +0.012982 | 30 | 27 | 0 |
| trend_crossover | TLT | neutral | 5 | 57 | 57 | +0.000960 | +0.001607 | -0.036953 | +0.025699 | 33 | 24 | 0 |
| trend_crossover | TLT | neutral | 20 | 57 | 57 | +0.001480 | +0.001377 | -0.071013 | +0.086349 | 29 | 28 | 0 |
| trend_alignment | GLD | bullish | 1 | 27 | 27 | +0.000067 | +0.000177 | -0.008761 | +0.012597 | 14 | 13 | 0 |
| trend_alignment | GLD | bullish | 5 | 27 | 27 | +0.000447 | -0.000794 | -0.040608 | +0.033844 | 13 | 14 | 0 |
| trend_alignment | GLD | bullish | 20 | 27 | 27 | +0.013534 | +0.014799 | -0.065923 | +0.102921 | 16 | 11 | 0 |
| trend_alignment | GLD | bearish | 1 | 28 | 28 | -0.000068 | +0.000100 | -0.013513 | +0.011318 | 15 | 13 | 0 |
| trend_alignment | GLD | bearish | 5 | 28 | 28 | +0.001874 | +0.003054 | -0.035074 | +0.024597 | 18 | 10 | 0 |
| trend_alignment | GLD | bearish | 20 | 28 | 28 | +0.012372 | +0.015200 | -0.058288 | +0.082544 | 15 | 13 | 0 |
| trend_alignment | GLD | neutral | 1 | 48 | 48 | +0.000322 | +0.000097 | -0.008015 | +0.009965 | 24 | 23 | 1 |
| trend_alignment | GLD | neutral | 5 | 48 | 48 | +0.000054 | -0.000833 | -0.053973 | +0.052901 | 23 | 25 | 0 |
| trend_alignment | GLD | neutral | 20 | 48 | 48 | +0.011586 | +0.005098 | -0.058840 | +0.128098 | 29 | 19 | 0 |
| momentum_in_trend_context | GLD | bullish | 1 | 91 | 91 | -0.000829 | -0.000853 | -0.016134 | +0.012597 | 39 | 52 | 0 |
| momentum_in_trend_context | GLD | bullish | 5 | 91 | 91 | +0.000217 | -0.000173 | -0.043239 | +0.046828 | 45 | 46 | 0 |
| momentum_in_trend_context | GLD | bullish | 20 | 91 | 91 | +0.010888 | +0.014507 | -0.068572 | +0.126679 | 53 | 38 | 0 |
| momentum_in_trend_context | GLD | bearish | 1 | 90 | 90 | +0.000162 | +0.000155 | -0.021312 | +0.011318 | 47 | 42 | 1 |
| momentum_in_trend_context | GLD | bearish | 5 | 90 | 90 | +0.000313 | +0.000132 | -0.044526 | +0.052754 | 46 | 44 | 0 |
| momentum_in_trend_context | GLD | bearish | 20 | 90 | 90 | +0.006729 | +0.002970 | -0.077309 | +0.114880 | 48 | 40 | 2 |
| momentum_in_trend_context | GLD | neutral | 1 | 182 | 182 | +0.000692 | +0.000377 | -0.024682 | +0.030131 | 98 | 81 | 3 |
| momentum_in_trend_context | GLD | neutral | 5 | 182 | 182 | +0.001505 | +0.000538 | -0.071471 | +0.064945 | 94 | 88 | 0 |
| momentum_in_trend_context | GLD | neutral | 20 | 182 | 182 | +0.009196 | +0.004019 | -0.075457 | +0.096209 | 102 | 80 | 0 |
| trend_crossover | GLD | bullish | 1 | 27 | 27 | -0.000183 | +0.000156 | -0.008761 | +0.012597 | 14 | 13 | 0 |
| trend_crossover | GLD | bullish | 5 | 27 | 27 | -0.003019 | -0.004847 | -0.040608 | +0.033670 | 10 | 17 | 0 |
| trend_crossover | GLD | bullish | 20 | 27 | 27 | +0.009965 | +0.013129 | -0.065923 | +0.128098 | 16 | 11 | 0 |
| trend_crossover | GLD | bearish | 1 | 28 | 28 | +0.000541 | -0.000000 | -0.006968 | +0.011318 | 14 | 14 | 0 |
| trend_crossover | GLD | bearish | 5 | 28 | 28 | +0.000138 | -0.000271 | -0.035074 | +0.052901 | 14 | 14 | 0 |
| trend_crossover | GLD | bearish | 20 | 28 | 28 | +0.010722 | +0.000213 | -0.054965 | +0.092574 | 14 | 14 | 0 |
| trend_crossover | GLD | neutral | 1 | 56 | 56 | -0.000117 | -0.000102 | -0.013513 | +0.010283 | 28 | 28 | 0 |
| trend_crossover | GLD | neutral | 5 | 56 | 56 | -0.001890 | -0.003511 | -0.036992 | +0.033844 | 25 | 31 | 0 |
| trend_crossover | GLD | neutral | 20 | 56 | 56 | +0.010221 | +0.007548 | -0.064222 | +0.102921 | 31 | 25 | 0 |

## D2 — Gate decomposition on common timestamps (trend_alignment × momentum_in_trend_context)

| symbol | trend state | momentum state | count |
|---|---|---|---|
| SPY | bullish | bullish | 1166 |
| SPY | bullish | bearish | 0 |
| SPY | bullish | neutral | 543 |
| SPY | bullish | insufficient_data | 0 |
| SPY | bearish | bullish | 0 |
| SPY | bearish | bearish | 270 |
| SPY | bearish | neutral | 454 |
| SPY | bearish | insufficient_data | 0 |
| SPY | neutral | bullish | 23 |
| SPY | neutral | bearish | 9 |
| SPY | neutral | neutral | 51 |
| SPY | neutral | insufficient_data | 0 |
| SPY | insufficient_data | bullish | 0 |
| SPY | insufficient_data | bearish | 0 |
| SPY | insufficient_data | neutral | 0 |
| SPY | insufficient_data | insufficient_data | 0 |
| QQQ | bullish | bullish | 1171 |
| QQQ | bullish | bearish | 0 |
| QQQ | bullish | neutral | 561 |
| QQQ | bullish | insufficient_data | 0 |
| QQQ | bearish | bullish | 0 |
| QQQ | bearish | bearish | 284 |
| QQQ | bearish | neutral | 438 |
| QQQ | bearish | insufficient_data | 0 |
| QQQ | neutral | bullish | 16 |
| QQQ | neutral | bearish | 4 |
| QQQ | neutral | neutral | 42 |
| QQQ | neutral | insufficient_data | 0 |
| QQQ | insufficient_data | bullish | 0 |
| QQQ | insufficient_data | bearish | 0 |
| QQQ | insufficient_data | neutral | 0 |
| QQQ | insufficient_data | insufficient_data | 0 |
| IWM | bullish | bullish | 852 |
| IWM | bullish | bearish | 0 |
| IWM | bullish | neutral | 728 |
| IWM | bullish | insufficient_data | 0 |
| IWM | bearish | bullish | 0 |
| IWM | bearish | bearish | 370 |
| IWM | bearish | neutral | 480 |
| IWM | bearish | insufficient_data | 0 |
| IWM | neutral | bullish | 22 |
| IWM | neutral | bearish | 12 |
| IWM | neutral | neutral | 52 |
| IWM | neutral | insufficient_data | 0 |
| IWM | insufficient_data | bullish | 0 |
| IWM | insufficient_data | bearish | 0 |
| IWM | insufficient_data | neutral | 0 |
| IWM | insufficient_data | insufficient_data | 0 |
| TLT | bullish | bullish | 582 |
| TLT | bullish | bearish | 0 |
| TLT | bullish | neutral | 579 |
| TLT | bullish | insufficient_data | 0 |
| TLT | bearish | bullish | 0 |
| TLT | bearish | bearish | 681 |
| TLT | bearish | neutral | 562 |
| TLT | bearish | insufficient_data | 0 |
| TLT | neutral | bullish | 17 |
| TLT | neutral | bearish | 15 |
| TLT | neutral | neutral | 80 |
| TLT | neutral | insufficient_data | 0 |
| TLT | insufficient_data | bullish | 0 |
| TLT | insufficient_data | bearish | 0 |
| TLT | insufficient_data | neutral | 0 |
| TLT | insufficient_data | insufficient_data | 0 |
| GLD | bullish | bullish | 776 |
| GLD | bullish | bearish | 0 |
| GLD | bullish | neutral | 549 |
| GLD | bullish | insufficient_data | 0 |
| GLD | bearish | bullish | 0 |
| GLD | bearish | bearish | 485 |
| GLD | bearish | neutral | 614 |
| GLD | bearish | insufficient_data | 0 |
| GLD | neutral | bullish | 11 |
| GLD | neutral | bearish | 11 |
| GLD | neutral | neutral | 70 |
| GLD | neutral | insufficient_data | 0 |
| GLD | insufficient_data | bullish | 0 |
| GLD | insufficient_data | bearish | 0 |
| GLD | insufficient_data | neutral | 0 |
| GLD | insufficient_data | insufficient_data | 0 |

Partitions of trend-directional bars by the momentum state at the same bar; deltas are against the parent trend state's own evaluated sample:

| symbol | trend | h | partition | reason signature | n | mean | median | min | max | pos | neg | zero | mean delta | median delta |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SPY | bullish | 1 | retained |  | 1166 | +0.000136 | +0.000441 | -0.034836 | +0.030823 | 630 | 529 | 7 | +0.000064 | -0.000021 |
| SPY | bullish | 1 | removed |  | 543 | -0.000065 | +0.000583 | -0.038730 | +0.036484 | 292 | 247 | 4 | -0.000137 | +0.000120 |
| SPY | bullish | 1 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| SPY | bullish | 1 | removed | `fast_above_slow,momentum_depressed,momentum_contradicts_trend` | 187 | +0.000978 | +0.002941 | -0.038730 | +0.036484 | 113 | 72 | 2 | +0.000906 | +0.002478 |
| SPY | bullish | 1 | removed | `momentum_midrange` | 356 | -0.000613 | +0.000051 | -0.034814 | +0.030300 | 179 | 175 | 2 | -0.000685 | -0.000412 |
| SPY | bullish | 5 | retained |  | 1166 | +0.001569 | +0.003168 | -0.113155 | +0.054314 | 709 | 455 | 2 | -0.000099 | -0.000285 |
| SPY | bullish | 5 | removed |  | 543 | +0.001880 | +0.004487 | -0.113958 | +0.066894 | 322 | 221 | 0 | +0.000212 | +0.001034 |
| SPY | bullish | 5 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| SPY | bullish | 5 | removed | `fast_above_slow,momentum_depressed,momentum_contradicts_trend` | 187 | +0.007277 | +0.007323 | -0.113958 | +0.066894 | 130 | 57 | 0 | +0.005609 | +0.003869 |
| SPY | bullish | 5 | removed | `momentum_midrange` | 356 | -0.000955 | +0.001885 | -0.083184 | +0.064456 | 192 | 164 | 0 | -0.002622 | -0.001569 |
| SPY | bullish | 20 | retained |  | 1166 | +0.004907 | +0.011735 | -0.289394 | +0.113178 | 757 | 409 | 0 | -0.001282 | -0.001873 |
| SPY | bullish | 20 | removed |  | 543 | +0.008941 | +0.017338 | -0.311755 | +0.115151 | 390 | 153 | 0 | +0.002752 | +0.003730 |
| SPY | bullish | 20 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| SPY | bullish | 20 | removed | `fast_above_slow,momentum_depressed,momentum_contradicts_trend` | 187 | +0.008637 | +0.022723 | -0.311755 | +0.109357 | 136 | 51 | 0 | +0.002448 | +0.009115 |
| SPY | bullish | 20 | removed | `momentum_midrange` | 356 | +0.009101 | +0.015939 | -0.291948 | +0.115151 | 254 | 102 | 0 | +0.002912 | +0.002332 |
| SPY | bearish | 1 | retained |  | 270 | +0.000972 | +0.000937 | -0.056612 | +0.047994 | 146 | 124 | 0 | +0.000659 | +0.000369 |
| SPY | bearish | 1 | removed |  | 454 | -0.000079 | +0.000474 | -0.033113 | +0.024087 | 237 | 214 | 3 | -0.000392 | -0.000095 |
| SPY | bearish | 1 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| SPY | bearish | 1 | removed | `fast_below_slow,momentum_elevated,momentum_contradicts_trend` | 197 | -0.000219 | +0.000000 | -0.029170 | +0.012398 | 97 | 98 | 2 | -0.000532 | -0.000569 |
| SPY | bearish | 1 | removed | `momentum_midrange` | 257 | +0.000029 | +0.000592 | -0.033113 | +0.024087 | 140 | 116 | 1 | -0.000284 | +0.000024 |
| SPY | bearish | 5 | retained |  | 270 | +0.005778 | +0.009397 | -0.157357 | +0.117623 | 162 | 108 | 0 | +0.002360 | +0.003961 |
| SPY | bearish | 5 | removed |  | 454 | +0.002015 | +0.003614 | -0.096780 | +0.069159 | 259 | 194 | 1 | -0.001403 | -0.001822 |
| SPY | bearish | 5 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| SPY | bearish | 5 | removed | `fast_below_slow,momentum_elevated,momentum_contradicts_trend` | 197 | +0.003356 | +0.005395 | -0.051155 | +0.042987 | 124 | 73 | 0 | -0.000063 | -0.000040 |
| SPY | bearish | 5 | removed | `momentum_midrange` | 257 | +0.000988 | +0.001373 | -0.096780 | +0.069159 | 135 | 121 | 1 | -0.002431 | -0.004063 |
| SPY | bearish | 20 | retained |  | 270 | +0.025239 | +0.025077 | -0.192898 | +0.234015 | 181 | 89 | 0 | +0.007758 | +0.003970 |
| SPY | bearish | 20 | removed |  | 454 | +0.012868 | +0.019722 | -0.122714 | +0.182394 | 312 | 142 | 0 | -0.004614 | -0.001385 |
| SPY | bearish | 20 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| SPY | bearish | 20 | removed | `fast_below_slow,momentum_elevated,momentum_contradicts_trend` | 197 | +0.013818 | +0.020589 | -0.122714 | +0.082428 | 148 | 49 | 0 | -0.003664 | -0.000518 |
| SPY | bearish | 20 | removed | `momentum_midrange` | 257 | +0.012140 | +0.019540 | -0.107393 | +0.182394 | 164 | 93 | 0 | -0.005342 | -0.001567 |
| QQQ | bullish | 1 | retained |  | 1171 | +0.000065 | +0.000458 | -0.035860 | +0.027147 | 622 | 544 | 5 | -0.000082 | -0.000174 |
| QQQ | bullish | 1 | removed |  | 561 | +0.000317 | +0.001409 | -0.044640 | +0.044890 | 307 | 253 | 1 | +0.000170 | +0.000778 |
| QQQ | bullish | 1 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| QQQ | bullish | 1 | removed | `fast_above_slow,momentum_depressed,momentum_contradicts_trend` | 202 | +0.001336 | +0.003367 | -0.044640 | +0.044890 | 119 | 83 | 0 | +0.001190 | +0.002736 |
| QQQ | bullish | 1 | removed | `momentum_midrange` | 359 | -0.000257 | +0.000666 | -0.040090 | +0.044581 | 188 | 170 | 1 | -0.000403 | +0.000035 |
| QQQ | bullish | 5 | retained |  | 1171 | +0.001936 | +0.003442 | -0.119729 | +0.063369 | 689 | 481 | 1 | +0.000186 | -0.000500 |
| QQQ | bullish | 5 | removed |  | 561 | +0.001362 | +0.004930 | -0.158172 | +0.120874 | 331 | 230 | 0 | -0.000388 | +0.000988 |
| QQQ | bullish | 5 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| QQQ | bullish | 5 | removed | `fast_above_slow,momentum_depressed,momentum_contradicts_trend` | 202 | +0.002757 | +0.004816 | -0.158172 | +0.120874 | 120 | 82 | 0 | +0.001008 | +0.000874 |
| QQQ | bullish | 5 | removed | `momentum_midrange` | 359 | +0.000576 | +0.004930 | -0.115205 | +0.076760 | 211 | 148 | 0 | -0.001174 | +0.000988 |
| QQQ | bullish | 20 | retained |  | 1171 | +0.008548 | +0.015392 | -0.274946 | +0.132769 | 770 | 401 | 0 | -0.000629 | -0.001424 |
| QQQ | bullish | 20 | removed |  | 561 | +0.010488 | +0.019334 | -0.236461 | +0.126635 | 385 | 175 | 1 | +0.001312 | +0.002518 |
| QQQ | bullish | 20 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| QQQ | bullish | 20 | removed | `fast_above_slow,momentum_depressed,momentum_contradicts_trend` | 202 | +0.015131 | +0.030484 | -0.236461 | +0.126635 | 150 | 52 | 0 | +0.005955 | +0.013668 |
| QQQ | bullish | 20 | removed | `momentum_midrange` | 359 | +0.007875 | +0.013611 | -0.159595 | +0.113606 | 235 | 123 | 1 | -0.001301 | -0.003205 |
| QQQ | bearish | 1 | retained |  | 284 | +0.001000 | +0.001914 | -0.060746 | +0.067902 | 156 | 128 | 0 | +0.000214 | +0.000371 |
| QQQ | bearish | 1 | removed |  | 438 | +0.000648 | +0.001474 | -0.037427 | +0.033024 | 244 | 192 | 2 | -0.000138 | -0.000070 |
| QQQ | bearish | 1 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| QQQ | bearish | 1 | removed | `fast_below_slow,momentum_elevated,momentum_contradicts_trend` | 205 | +0.000627 | +0.001085 | -0.033308 | +0.022342 | 111 | 92 | 2 | -0.000160 | -0.000458 |
| QQQ | bearish | 1 | removed | `momentum_midrange` | 233 | +0.000667 | +0.002245 | -0.037427 | +0.033024 | 133 | 100 | 0 | -0.000120 | +0.000702 |
| QQQ | bearish | 5 | retained |  | 284 | +0.009456 | +0.012850 | -0.095493 | +0.106654 | 173 | 110 | 1 | +0.002711 | +0.003106 |
| QQQ | bearish | 5 | removed |  | 438 | +0.004987 | +0.008256 | -0.107232 | +0.082511 | 267 | 171 | 0 | -0.001758 | -0.001489 |
| QQQ | bearish | 5 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| QQQ | bearish | 5 | removed | `fast_below_slow,momentum_elevated,momentum_contradicts_trend` | 205 | +0.006138 | +0.007993 | -0.048017 | +0.067534 | 129 | 76 | 0 | -0.000607 | -0.001751 |
| QQQ | bearish | 5 | removed | `momentum_midrange` | 233 | +0.003975 | +0.009152 | -0.107232 | +0.082511 | 138 | 95 | 0 | -0.002770 | -0.000593 |
| QQQ | bearish | 20 | retained |  | 284 | +0.028310 | +0.028210 | -0.111125 | +0.244676 | 183 | 100 | 1 | +0.002002 | -0.001549 |
| QQQ | bearish | 20 | removed |  | 438 | +0.025009 | +0.030362 | -0.142223 | +0.185257 | 315 | 123 | 0 | -0.001298 | +0.000603 |
| QQQ | bearish | 20 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| QQQ | bearish | 20 | removed | `fast_below_slow,momentum_elevated,momentum_contradicts_trend` | 205 | +0.017628 | +0.023389 | -0.142223 | +0.112309 | 139 | 66 | 0 | -0.008679 | -0.006370 |
| QQQ | bearish | 20 | removed | `momentum_midrange` | 233 | +0.031503 | +0.036582 | -0.105309 | +0.185257 | 176 | 57 | 0 | +0.005195 | +0.006823 |
| IWM | bullish | 1 | retained |  | 852 | -0.000613 | +0.000000 | -0.041820 | +0.033298 | 425 | 423 | 4 | -0.000413 | -0.000344 |
| IWM | bullish | 1 | removed |  | 728 | +0.000283 | +0.000958 | -0.049087 | +0.057848 | 389 | 337 | 2 | +0.000483 | +0.000614 |
| IWM | bullish | 1 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| IWM | bullish | 1 | removed | `fast_above_slow,momentum_depressed,momentum_contradicts_trend` | 228 | +0.000731 | +0.002577 | -0.049087 | +0.034967 | 133 | 93 | 2 | +0.000931 | +0.002233 |
| IWM | bullish | 1 | removed | `momentum_midrange` | 500 | +0.000078 | +0.000340 | -0.032777 | +0.057848 | 256 | 244 | 0 | +0.000279 | -0.000004 |
| IWM | bullish | 5 | retained |  | 852 | -0.000681 | -0.000379 | -0.113530 | +0.094770 | 420 | 431 | 1 | -0.001112 | -0.001314 |
| IWM | bullish | 5 | removed |  | 728 | +0.001732 | +0.002963 | -0.084561 | +0.116946 | 396 | 332 | 0 | +0.001301 | +0.002027 |
| IWM | bullish | 5 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| IWM | bullish | 5 | removed | `fast_above_slow,momentum_depressed,momentum_contradicts_trend` | 228 | +0.006725 | +0.009407 | -0.070262 | +0.076902 | 147 | 81 | 0 | +0.006294 | +0.008472 |
| IWM | bullish | 5 | removed | `momentum_midrange` | 500 | -0.000544 | -0.000070 | -0.084561 | +0.116946 | 249 | 251 | 0 | -0.000975 | -0.001005 |
| IWM | bullish | 20 | retained |  | 852 | -0.002354 | -0.000041 | -0.404586 | +0.173913 | 425 | 426 | 1 | -0.004467 | -0.006076 |
| IWM | bullish | 20 | removed |  | 728 | +0.007341 | +0.014001 | -0.207827 | +0.201741 | 451 | 277 | 0 | +0.005228 | +0.007967 |
| IWM | bullish | 20 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| IWM | bullish | 20 | removed | `fast_above_slow,momentum_depressed,momentum_contradicts_trend` | 228 | +0.010741 | +0.021079 | -0.136989 | +0.201741 | 153 | 75 | 0 | +0.008628 | +0.015044 |
| IWM | bullish | 20 | removed | `momentum_midrange` | 500 | +0.005790 | +0.010252 | -0.207827 | +0.194725 | 298 | 202 | 0 | +0.003677 | +0.004217 |
| IWM | bearish | 1 | retained |  | 370 | +0.000207 | +0.000603 | -0.046032 | +0.051614 | 190 | 179 | 1 | +0.000198 | +0.000341 |
| IWM | bearish | 1 | removed |  | 480 | -0.000144 | +0.000105 | -0.040520 | +0.037771 | 241 | 239 | 0 | -0.000152 | -0.000156 |
| IWM | bearish | 1 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| IWM | bearish | 1 | removed | `fast_below_slow,momentum_elevated,momentum_contradicts_trend` | 178 | +0.000255 | +0.000371 | -0.029261 | +0.024916 | 94 | 84 | 0 | +0.000247 | +0.000109 |
| IWM | bearish | 1 | removed | `momentum_midrange` | 302 | -0.000379 | -0.000180 | -0.040520 | +0.037771 | 147 | 155 | 0 | -0.000388 | -0.000441 |
| IWM | bearish | 5 | retained |  | 370 | +0.001120 | +0.005803 | -0.230792 | +0.160709 | 202 | 167 | 1 | -0.001553 | +0.001392 |
| IWM | bearish | 5 | removed |  | 480 | +0.003871 | +0.003458 | -0.109278 | +0.127800 | 272 | 208 | 0 | +0.001197 | -0.000953 |
| IWM | bearish | 5 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| IWM | bearish | 5 | removed | `fast_below_slow,momentum_elevated,momentum_contradicts_trend` | 178 | +0.002365 | +0.001820 | -0.108339 | +0.050859 | 96 | 82 | 0 | -0.000309 | -0.002590 |
| IWM | bearish | 5 | removed | `momentum_midrange` | 302 | +0.004759 | +0.004372 | -0.109278 | +0.127800 | 176 | 126 | 0 | +0.002085 | -0.000039 |
| IWM | bearish | 20 | retained |  | 370 | +0.011559 | +0.010205 | -0.305699 | +0.246182 | 217 | 153 | 0 | -0.003758 | -0.006916 |
| IWM | bearish | 20 | removed |  | 480 | +0.018214 | +0.022937 | -0.140935 | +0.150915 | 321 | 159 | 0 | +0.002897 | +0.005817 |
| IWM | bearish | 20 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| IWM | bearish | 20 | removed | `fast_below_slow,momentum_elevated,momentum_contradicts_trend` | 178 | +0.020546 | +0.023533 | -0.100177 | +0.128739 | 116 | 62 | 0 | +0.005229 | +0.006413 |
| IWM | bearish | 20 | removed | `momentum_midrange` | 302 | +0.016840 | +0.022528 | -0.140935 | +0.150915 | 205 | 97 | 0 | +0.001523 | +0.005407 |
| TLT | bullish | 1 | retained |  | 582 | +0.000135 | +0.000239 | -0.064343 | +0.053968 | 301 | 275 | 6 | +0.000140 | +0.000138 |
| TLT | bullish | 1 | removed |  | 579 | -0.000146 | +0.000000 | -0.055548 | +0.039987 | 289 | 283 | 7 | -0.000141 | -0.000100 |
| TLT | bullish | 1 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| TLT | bullish | 1 | removed | `fast_above_slow,momentum_depressed,momentum_contradicts_trend` | 189 | +0.000249 | +0.000244 | -0.021364 | +0.016346 | 98 | 90 | 1 | +0.000254 | +0.000144 |
| TLT | bullish | 1 | removed | `momentum_midrange` | 390 | -0.000337 | +0.000000 | -0.055548 | +0.039987 | 191 | 193 | 6 | -0.000332 | -0.000100 |
| TLT | bullish | 5 | retained |  | 582 | +0.000178 | +0.000853 | -0.140480 | +0.113647 | 306 | 275 | 1 | -0.000233 | +0.000021 |
| TLT | bullish | 5 | removed |  | 579 | +0.000646 | +0.000831 | -0.045450 | +0.106090 | 306 | 273 | 0 | +0.000235 | +0.000000 |
| TLT | bullish | 5 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| TLT | bullish | 5 | removed | `fast_above_slow,momentum_depressed,momentum_contradicts_trend` | 189 | +0.004026 | +0.004006 | -0.036564 | +0.106090 | 119 | 70 | 0 | +0.003615 | +0.003175 |
| TLT | bullish | 5 | removed | `momentum_midrange` | 390 | -0.000992 | -0.000716 | -0.045450 | +0.065886 | 187 | 203 | 0 | -0.001404 | -0.001548 |
| TLT | bullish | 20 | retained |  | 582 | -0.000800 | -0.005994 | -0.086669 | +0.180496 | 252 | 330 | 0 | -0.001123 | -0.003285 |
| TLT | bullish | 20 | removed |  | 579 | +0.001451 | +0.001158 | -0.091340 | +0.157469 | 297 | 282 | 0 | +0.001129 | +0.003867 |
| TLT | bullish | 20 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| TLT | bullish | 20 | removed | `fast_above_slow,momentum_depressed,momentum_contradicts_trend` | 189 | +0.008544 | +0.009700 | -0.071283 | +0.157469 | 113 | 76 | 0 | +0.008222 | +0.012410 |
| TLT | bullish | 20 | removed | `momentum_midrange` | 390 | -0.001986 | -0.002460 | -0.091340 | +0.120805 | 184 | 206 | 0 | -0.002309 | +0.000250 |
| TLT | bearish | 1 | retained |  | 681 | +0.000050 | +0.000198 | -0.022487 | +0.030152 | 347 | 334 | 0 | -0.000021 | +0.000082 |
| TLT | bearish | 1 | removed |  | 562 | +0.000097 | +0.000083 | -0.024099 | +0.025303 | 286 | 274 | 2 | +0.000026 | -0.000033 |
| TLT | bearish | 1 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| TLT | bearish | 1 | removed | `fast_below_slow,momentum_elevated,momentum_contradicts_trend` | 173 | -0.000726 | -0.000731 | -0.024099 | +0.025303 | 77 | 96 | 0 | -0.000798 | -0.000847 |
| TLT | bearish | 1 | removed | `momentum_midrange` | 389 | +0.000463 | +0.000319 | -0.015221 | +0.023468 | 209 | 178 | 2 | +0.000392 | +0.000203 |
| TLT | bearish | 5 | retained |  | 681 | -0.001852 | -0.000939 | -0.074111 | +0.059957 | 322 | 357 | 2 | -0.000546 | -0.000600 |
| TLT | bearish | 5 | removed |  | 562 | -0.000645 | +0.000345 | -0.051618 | +0.061270 | 283 | 279 | 0 | +0.000661 | +0.000684 |
| TLT | bearish | 5 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| TLT | bearish | 5 | removed | `fast_below_slow,momentum_elevated,momentum_contradicts_trend` | 173 | -0.000941 | -0.001410 | -0.040855 | +0.061270 | 78 | 95 | 0 | +0.000366 | -0.001072 |
| TLT | bearish | 5 | removed | `momentum_midrange` | 389 | -0.000514 | +0.001085 | -0.051618 | +0.044805 | 205 | 184 | 0 | +0.000793 | +0.001424 |
| TLT | bearish | 20 | retained |  | 681 | -0.008982 | -0.007168 | -0.115699 | +0.166809 | 303 | 378 | 0 | -0.003816 | -0.002470 |
| TLT | bearish | 20 | removed |  | 562 | -0.000542 | +0.001284 | -0.111802 | +0.109071 | 288 | 274 | 0 | +0.004624 | +0.005982 |
| TLT | bearish | 20 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| TLT | bearish | 20 | removed | `fast_below_slow,momentum_elevated,momentum_contradicts_trend` | 173 | +0.002260 | +0.000083 | -0.085860 | +0.099712 | 87 | 86 | 0 | +0.007426 | +0.004781 |
| TLT | bearish | 20 | removed | `momentum_midrange` | 389 | -0.001788 | +0.001708 | -0.111802 | +0.109071 | 201 | 188 | 0 | +0.003378 | +0.006406 |
| GLD | bullish | 1 | retained |  | 776 | +0.000020 | +0.000000 | -0.029848 | +0.025932 | 387 | 387 | 2 | -0.000050 | +0.000000 |
| GLD | bullish | 1 | removed |  | 549 | +0.000140 | -0.000053 | -0.041092 | +0.030131 | 269 | 275 | 5 | +0.000070 | -0.000053 |
| GLD | bullish | 1 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| GLD | bullish | 1 | removed | `fast_above_slow,momentum_depressed,momentum_contradicts_trend` | 194 | -0.000312 | -0.000400 | -0.041092 | +0.029660 | 87 | 106 | 1 | -0.000382 | -0.000400 |
| GLD | bullish | 1 | removed | `momentum_midrange` | 355 | +0.000388 | +0.000156 | -0.024682 | +0.030131 | 182 | 169 | 4 | +0.000318 | +0.000156 |
| GLD | bullish | 5 | retained |  | 776 | +0.001791 | +0.002428 | -0.096595 | +0.084434 | 429 | 345 | 2 | -0.000114 | +0.000703 |
| GLD | bullish | 5 | removed |  | 549 | +0.002066 | +0.000878 | -0.076161 | +0.089048 | 283 | 266 | 0 | +0.000161 | -0.000847 |
| GLD | bullish | 5 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| GLD | bullish | 5 | removed | `fast_above_slow,momentum_depressed,momentum_contradicts_trend` | 194 | +0.002923 | -0.000390 | -0.076161 | +0.089048 | 94 | 100 | 0 | +0.001018 | -0.002115 |
| GLD | bullish | 5 | removed | `momentum_midrange` | 355 | +0.001597 | +0.001381 | -0.071471 | +0.064945 | 189 | 166 | 0 | -0.000308 | -0.000344 |
| GLD | bullish | 20 | retained |  | 776 | +0.006301 | +0.004052 | -0.116025 | +0.140865 | 415 | 359 | 2 | -0.001135 | -0.000036 |
| GLD | bullish | 20 | removed |  | 549 | +0.009040 | +0.004187 | -0.077077 | +0.173379 | 303 | 245 | 1 | +0.001604 | +0.000098 |
| GLD | bullish | 20 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| GLD | bullish | 20 | removed | `fast_above_slow,momentum_depressed,momentum_contradicts_trend` | 194 | +0.012059 | +0.004716 | -0.077077 | +0.173379 | 112 | 82 | 0 | +0.004624 | +0.000627 |
| GLD | bullish | 20 | removed | `momentum_midrange` | 355 | +0.007390 | +0.002745 | -0.075342 | +0.125867 | 191 | 163 | 1 | -0.000046 | -0.001343 |
| GLD | bearish | 1 | retained |  | 485 | -0.000082 | +0.000000 | -0.021312 | +0.019236 | 241 | 242 | 2 | +0.000050 | +0.000092 |
| GLD | bearish | 1 | removed |  | 614 | -0.000171 | -0.000272 | -0.022290 | +0.022181 | 290 | 321 | 3 | -0.000039 | -0.000180 |
| GLD | bearish | 1 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| GLD | bearish | 1 | removed | `fast_below_slow,momentum_elevated,momentum_contradicts_trend` | 202 | +0.000018 | -0.000383 | -0.022290 | +0.016851 | 94 | 108 | 0 | +0.000149 | -0.000291 |
| GLD | bearish | 1 | removed | `momentum_midrange` | 412 | -0.000263 | -0.000168 | -0.022043 | +0.022181 | 196 | 213 | 3 | -0.000132 | -0.000076 |
| GLD | bearish | 5 | retained |  | 485 | +0.001098 | +0.001901 | -0.049478 | +0.055050 | 264 | 219 | 2 | +0.000202 | +0.001311 |
| GLD | bearish | 5 | removed |  | 614 | +0.000737 | +0.000000 | -0.057763 | +0.057247 | 306 | 306 | 2 | -0.000160 | -0.000590 |
| GLD | bearish | 5 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| GLD | bearish | 5 | removed | `fast_below_slow,momentum_elevated,momentum_contradicts_trend` | 202 | -0.000410 | -0.002242 | -0.047425 | +0.053386 | 93 | 108 | 1 | -0.001306 | -0.002832 |
| GLD | bearish | 5 | removed | `momentum_midrange` | 412 | +0.001299 | +0.000601 | -0.057763 | +0.057247 | 213 | 198 | 1 | +0.000402 | +0.000011 |
| GLD | bearish | 20 | retained |  | 485 | +0.005992 | +0.005222 | -0.084254 | +0.114880 | 275 | 208 | 2 | +0.001305 | +0.002877 |
| GLD | bearish | 20 | removed |  | 614 | +0.003656 | -0.000013 | -0.100322 | +0.147566 | 307 | 307 | 0 | -0.001031 | -0.002358 |
| GLD | bearish | 20 | opposite |  | 0 |  |  |  |  | 0 | 0 | 0 |  |  |
| GLD | bearish | 20 | removed | `fast_below_slow,momentum_elevated,momentum_contradicts_trend` | 202 | +0.002898 | +0.005558 | -0.098553 | +0.147566 | 108 | 94 | 0 | -0.001789 | +0.003213 |
| GLD | bearish | 20 | removed | `momentum_midrange` | 412 | +0.004028 | -0.001476 | -0.100322 | +0.108775 | 199 | 213 | 0 | -0.000659 | -0.003821 |

## D3 — Predeclared temporal segments

Segments: `2015-2016` [2015-01-01T00:00:00+00:00, 2017-01-01T00:00:00+00:00), `2017-2018` [2017-01-01T00:00:00+00:00, 2019-01-01T00:00:00+00:00), `2019-2020` [2019-01-01T00:00:00+00:00, 2021-01-01T00:00:00+00:00), `2021-2022` [2021-01-01T00:00:00+00:00, 2023-01-01T00:00:00+00:00), `2023-2024` [2023-01-01T00:00:00+00:00, 2025-01-01T00:00:00+00:00)

### trend_alignment

| symbol | segment | h | state | n | episodes | mean | median | min | max | pos | neg | zero | mean delta | median delta |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SPY | 2015-2016 | 1 | all | 504 | 1 | +0.000303 | +0.000444 | -0.041754 | +0.027560 | 265 | 235 | 4 |  |  |
| SPY | 2015-2016 | 1 | bullish | 267 | 9 | +0.000395 | +0.000229 | -0.017007 | +0.019503 | 139 | 125 | 3 | +0.000092 | -0.000215 |
| SPY | 2015-2016 | 1 | bearish | 190 | 7 | +0.000129 | +0.000364 | -0.041754 | +0.027560 | 99 | 90 | 1 | -0.000174 | -0.000080 |
| SPY | 2015-2016 | 1 | neutral | 47 | 15 | +0.000486 | +0.000985 | -0.012945 | +0.014388 | 27 | 20 | 0 | +0.000183 | +0.000541 |
| SPY | 2015-2016 | 5 | all | 504 | 1 | +0.001341 | +0.002023 | -0.104357 | +0.062883 | 285 | 218 | 1 |  |  |
| SPY | 2015-2016 | 5 | bullish | 267 | 9 | +0.001288 | +0.000669 | -0.041767 | +0.041322 | 146 | 121 | 0 | -0.000053 | -0.001354 |
| SPY | 2015-2016 | 5 | bearish | 190 | 7 | +0.002844 | +0.003170 | -0.054015 | +0.062883 | 110 | 79 | 1 | +0.001502 | +0.001147 |
| SPY | 2015-2016 | 5 | neutral | 47 | 15 | -0.004431 | +0.003752 | -0.104357 | +0.031192 | 29 | 18 | 0 | -0.005772 | +0.001729 |
| SPY | 2015-2016 | 20 | all | 504 | 1 | +0.005167 | +0.006208 | -0.106024 | +0.100437 | 303 | 201 | 0 |  |  |
| SPY | 2015-2016 | 20 | bullish | 267 | 9 | +0.000011 | +0.002392 | -0.098800 | +0.075789 | 152 | 115 | 0 | -0.005156 | -0.003817 |
| SPY | 2015-2016 | 20 | bearish | 190 | 7 | +0.015025 | +0.018117 | -0.106024 | +0.100437 | 129 | 61 | 0 | +0.009857 | +0.011909 |
| SPY | 2015-2016 | 20 | neutral | 47 | 15 | -0.005391 | -0.000190 | -0.088762 | +0.055391 | 22 | 25 | 0 | -0.010558 | -0.006398 |
| SPY | 2017-2018 | 1 | all | 502 | 1 | -0.000196 | +0.000143 | -0.038730 | +0.043268 | 261 | 235 | 6 |  |  |
| SPY | 2017-2018 | 1 | bullish | 365 | 4 | +0.000127 | +0.000245 | -0.038730 | +0.035354 | 196 | 164 | 5 | +0.000323 | +0.000102 |
| SPY | 2017-2018 | 1 | bearish | 120 | 3 | -0.001467 | -0.000902 | -0.029305 | +0.043268 | 53 | 66 | 1 | -0.001271 | -0.001045 |
| SPY | 2017-2018 | 1 | neutral | 17 | 5 | +0.001840 | +0.001161 | -0.002167 | +0.013738 | 12 | 5 | 0 | +0.002036 | +0.001018 |
| SPY | 2017-2018 | 5 | all | 502 | 1 | +0.000777 | +0.002563 | -0.088880 | +0.060219 | 305 | 195 | 2 |  |  |
| SPY | 2017-2018 | 5 | bullish | 365 | 4 | +0.002098 | +0.002787 | -0.080156 | +0.046894 | 233 | 130 | 2 | +0.001320 | +0.000224 |
| SPY | 2017-2018 | 5 | bearish | 120 | 3 | -0.003713 | -0.001338 | -0.088880 | +0.060219 | 57 | 63 | 0 | -0.004490 | -0.003901 |
| SPY | 2017-2018 | 5 | neutral | 17 | 5 | +0.004130 | +0.004344 | -0.005748 | +0.014399 | 15 | 2 | 0 | +0.003352 | +0.001781 |
| SPY | 2017-2018 | 20 | all | 502 | 1 | +0.005422 | +0.013065 | -0.122714 | +0.116879 | 340 | 162 | 0 |  |  |
| SPY | 2017-2018 | 20 | bullish | 365 | 4 | +0.008677 | +0.014184 | -0.095006 | +0.069767 | 261 | 104 | 0 | +0.003255 | +0.001119 |
| SPY | 2017-2018 | 20 | bearish | 120 | 3 | -0.006617 | +0.003660 | -0.122714 | +0.116879 | 63 | 57 | 0 | -0.012039 | -0.009405 |
| SPY | 2017-2018 | 20 | neutral | 17 | 5 | +0.020518 | +0.023903 | -0.014570 | +0.032936 | 16 | 1 | 0 | +0.015096 | +0.010838 |
| SPY | 2019-2020 | 1 | all | 505 | 1 | +0.000304 | +0.000804 | -0.056612 | +0.046810 | 284 | 218 | 3 |  |  |
| SPY | 2019-2020 | 1 | bullish | 381 | 5 | +0.000012 | +0.000843 | -0.034852 | +0.036484 | 216 | 163 | 2 | -0.000293 | +0.000038 |
| SPY | 2019-2020 | 1 | bearish | 117 | 5 | +0.001057 | +0.000640 | -0.056612 | +0.046810 | 65 | 51 | 1 | +0.000752 | -0.000164 |
| SPY | 2019-2020 | 1 | neutral | 7 | 7 | +0.003669 | -0.000333 | -0.002295 | +0.022017 | 3 | 4 | 0 | +0.003364 | -0.001137 |
| SPY | 2019-2020 | 5 | all | 505 | 1 | +0.003847 | +0.006416 | -0.157357 | +0.117623 | 331 | 174 | 0 |  |  |
| SPY | 2019-2020 | 5 | bullish | 381 | 5 | +0.002928 | +0.005686 | -0.113958 | +0.066894 | 254 | 127 | 0 | -0.000919 | -0.000731 |
| SPY | 2019-2020 | 5 | bearish | 117 | 5 | +0.007199 | +0.010464 | -0.157357 | +0.117623 | 73 | 44 | 0 | +0.003353 | +0.004047 |
| SPY | 2019-2020 | 5 | neutral | 7 | 7 | -0.002186 | +0.005808 | -0.057820 | +0.020525 | 4 | 3 | 0 | -0.006033 | -0.000608 |
| SPY | 2019-2020 | 20 | all | 505 | 1 | +0.016576 | +0.025657 | -0.311755 | +0.234015 | 383 | 122 | 0 |  |  |
| SPY | 2019-2020 | 20 | bullish | 381 | 5 | +0.009543 | +0.023363 | -0.311755 | +0.115151 | 282 | 99 | 0 | -0.007033 | -0.002295 |
| SPY | 2019-2020 | 20 | bearish | 117 | 5 | +0.040790 | +0.038788 | -0.192898 | +0.234015 | 97 | 20 | 0 | +0.024214 | +0.013131 |
| SPY | 2019-2020 | 20 | neutral | 7 | 7 | -0.005332 | +0.032231 | -0.158010 | +0.050998 | 4 | 3 | 0 | -0.021908 | +0.006573 |
| SPY | 2021-2022 | 1 | all | 503 | 1 | +0.000132 | +0.000494 | -0.033573 | +0.047994 | 264 | 238 | 1 |  |  |
| SPY | 2021-2022 | 1 | bullish | 330 | 5 | -0.000300 | +0.000209 | -0.033573 | +0.030823 | 170 | 159 | 1 | -0.000433 | -0.000286 |
| SPY | 2021-2022 | 1 | bearish | 169 | 4 | +0.000906 | +0.001081 | -0.029630 | +0.047994 | 92 | 77 | 0 | +0.000774 | +0.000587 |
| SPY | 2021-2022 | 1 | neutral | 4 | 4 | +0.003127 | +0.003500 | -0.002591 | +0.008099 | 2 | 2 | 0 | +0.002994 | +0.003005 |
| SPY | 2021-2022 | 5 | all | 503 | 1 | +0.000567 | +0.003218 | -0.096780 | +0.067221 | 273 | 230 | 0 |  |  |
| SPY | 2021-2022 | 5 | bullish | 330 | 5 | -0.001349 | +0.000794 | -0.073619 | +0.050123 | 172 | 158 | 0 | -0.001916 | -0.002424 |
| SPY | 2021-2022 | 5 | bearish | 169 | 4 | +0.004126 | +0.006654 | -0.096780 | +0.067221 | 98 | 71 | 0 | +0.003559 | +0.003436 |
| SPY | 2021-2022 | 5 | neutral | 4 | 4 | +0.008222 | +0.013640 | -0.012270 | +0.017880 | 3 | 1 | 0 | +0.007655 | +0.010421 |
| SPY | 2021-2022 | 20 | all | 503 | 1 | +0.002871 | +0.010213 | -0.126366 | +0.124140 | 297 | 206 | 0 |  |  |
| SPY | 2021-2022 | 20 | bullish | 330 | 5 | -0.005208 | +0.005845 | -0.126366 | +0.070227 | 185 | 145 | 0 | -0.008080 | -0.004368 |
| SPY | 2021-2022 | 20 | bearish | 169 | 4 | +0.018884 | +0.030999 | -0.095474 | +0.124140 | 110 | 59 | 0 | +0.016012 | +0.020786 |
| SPY | 2021-2022 | 20 | neutral | 4 | 4 | -0.007095 | -0.003261 | -0.085296 | +0.063437 | 2 | 2 | 0 | -0.009966 | -0.013474 |
| SPY | 2023-2024 | 1 | all | 502 | 1 | +0.000391 | +0.000653 | -0.029306 | +0.024016 | 282 | 220 | 0 |  |  |
| SPY | 2023-2024 | 1 | bullish | 366 | 5 | +0.000181 | +0.000537 | -0.029306 | +0.016123 | 201 | 165 | 0 | -0.000210 | -0.000116 |
| SPY | 2023-2024 | 1 | bearish | 128 | 5 | +0.000791 | +0.001351 | -0.018847 | +0.024016 | 74 | 54 | 0 | +0.000400 | +0.000698 |
| SPY | 2023-2024 | 1 | neutral | 8 | 8 | +0.003589 | +0.001270 | -0.000848 | +0.013337 | 7 | 1 | 0 | +0.003198 | +0.000617 |
| SPY | 2023-2024 | 5 | all | 502 | 1 | +0.003949 | +0.005523 | -0.061368 | +0.051093 | 313 | 189 | 0 |  |  |
| SPY | 2023-2024 | 5 | bullish | 366 | 5 | +0.002923 | +0.004525 | -0.061368 | +0.049094 | 226 | 140 | 0 | -0.001026 | -0.000998 |
| SPY | 2023-2024 | 5 | bearish | 128 | 5 | +0.006568 | +0.008695 | -0.040832 | +0.051093 | 83 | 45 | 0 | +0.002619 | +0.003173 |
| SPY | 2023-2024 | 5 | neutral | 8 | 8 | +0.008983 | +0.001808 | -0.002607 | +0.033740 | 4 | 4 | 0 | +0.005034 | -0.003715 |
| SPY | 2023-2024 | 20 | all | 502 | 1 | +0.016526 | +0.021535 | -0.076197 | +0.101712 | 366 | 136 | 0 |  |  |
| SPY | 2023-2024 | 20 | bullish | 366 | 5 | +0.014999 | +0.021208 | -0.076197 | +0.101712 | 267 | 99 | 0 | -0.001527 | -0.000327 |
| SPY | 2023-2024 | 20 | bearish | 128 | 5 | +0.020566 | +0.022118 | -0.059790 | +0.099254 | 94 | 34 | 0 | +0.004040 | +0.000583 |
| SPY | 2023-2024 | 20 | neutral | 8 | 8 | +0.021763 | +0.033290 | -0.022635 | +0.057426 | 5 | 3 | 0 | +0.005237 | +0.011755 |
| QQQ | 2015-2016 | 1 | all | 504 | 1 | +0.000157 | +0.000554 | -0.038993 | +0.044890 | 263 | 238 | 3 |  |  |
| QQQ | 2015-2016 | 1 | bullish | 300 | 9 | -0.000029 | -0.000091 | -0.030027 | +0.044890 | 147 | 152 | 1 | -0.000186 | -0.000644 |
| QQQ | 2015-2016 | 1 | bearish | 179 | 8 | +0.000834 | +0.001994 | -0.038407 | +0.031845 | 107 | 70 | 2 | +0.000677 | +0.001440 |
| QQQ | 2015-2016 | 1 | neutral | 25 | 15 | -0.002464 | -0.001942 | -0.038993 | +0.013002 | 9 | 16 | 0 | -0.002621 | -0.002496 |
| QQQ | 2015-2016 | 5 | all | 504 | 1 | +0.001794 | +0.003123 | -0.115205 | +0.120874 | 294 | 210 | 0 |  |  |
| QQQ | 2015-2016 | 5 | bullish | 300 | 9 | -0.000663 | +0.001285 | -0.115205 | +0.120874 | 166 | 134 | 0 | -0.002457 | -0.001838 |
| QQQ | 2015-2016 | 5 | bearish | 179 | 8 | +0.006090 | +0.009526 | -0.070878 | +0.061492 | 115 | 64 | 0 | +0.004296 | +0.006403 |
| QQQ | 2015-2016 | 5 | neutral | 25 | 15 | +0.000519 | +0.005295 | -0.052014 | +0.042840 | 13 | 12 | 0 | -0.001275 | +0.002173 |
| QQQ | 2015-2016 | 20 | all | 504 | 1 | +0.008176 | +0.011022 | -0.119242 | +0.129365 | 317 | 186 | 1 |  |  |
| QQQ | 2015-2016 | 20 | bullish | 300 | 9 | -0.000690 | +0.004169 | -0.119242 | +0.121511 | 167 | 133 | 0 | -0.008866 | -0.006852 |
| QQQ | 2015-2016 | 20 | bearish | 179 | 8 | +0.023573 | +0.025446 | -0.087572 | +0.129365 | 134 | 44 | 1 | +0.015397 | +0.014424 |
| QQQ | 2015-2016 | 20 | neutral | 25 | 15 | +0.004322 | +0.015066 | -0.110328 | +0.075297 | 16 | 9 | 0 | -0.003853 | +0.004044 |
| QQQ | 2017-2018 | 1 | all | 502 | 1 | -0.000000 | +0.000634 | -0.044664 | +0.050869 | 274 | 225 | 3 |  |  |
| QQQ | 2017-2018 | 1 | bullish | 402 | 4 | +0.000166 | +0.000660 | -0.044640 | +0.041717 | 222 | 177 | 3 | +0.000167 | +0.000025 |
| QQQ | 2017-2018 | 1 | bearish | 89 | 3 | -0.000858 | +0.000236 | -0.044664 | +0.050869 | 45 | 44 | 0 | -0.000857 | -0.000398 |
| QQQ | 2017-2018 | 1 | neutral | 11 | 5 | +0.000845 | +0.000762 | -0.014162 | +0.015859 | 7 | 4 | 0 | +0.000845 | +0.000128 |
| QQQ | 2017-2018 | 5 | all | 502 | 1 | +0.002217 | +0.004826 | -0.095493 | +0.067549 | 306 | 194 | 2 |  |  |
| QQQ | 2017-2018 | 5 | bullish | 402 | 4 | +0.003009 | +0.005421 | -0.082785 | +0.064773 | 256 | 145 | 1 | +0.000792 | +0.000595 |
| QQQ | 2017-2018 | 5 | bearish | 89 | 3 | -0.001921 | +0.001005 | -0.095493 | +0.067549 | 45 | 43 | 1 | -0.004138 | -0.003821 |
| QQQ | 2017-2018 | 5 | neutral | 11 | 5 | +0.006765 | -0.000059 | -0.008290 | +0.048121 | 5 | 6 | 0 | +0.004548 | -0.004886 |
| QQQ | 2017-2018 | 20 | all | 502 | 1 | +0.010890 | +0.015325 | -0.126057 | +0.124897 | 347 | 155 | 0 |  |  |
| QQQ | 2017-2018 | 20 | bullish | 402 | 4 | +0.013686 | +0.016477 | -0.122467 | +0.112711 | 296 | 106 | 0 | +0.002796 | +0.001152 |
| QQQ | 2017-2018 | 20 | bearish | 89 | 3 | +0.000529 | +0.003274 | -0.126057 | +0.124897 | 46 | 43 | 0 | -0.010360 | -0.012051 |
| QQQ | 2017-2018 | 20 | neutral | 11 | 5 | -0.007480 | -0.010776 | -0.067536 | +0.045987 | 5 | 6 | 0 | -0.018370 | -0.026101 |
| QQQ | 2019-2020 | 1 | all | 505 | 1 | +0.000669 | +0.001106 | -0.060746 | +0.043672 | 278 | 225 | 2 |  |  |
| QQQ | 2019-2020 | 1 | bullish | 391 | 5 | +0.000702 | +0.001283 | -0.035860 | +0.036097 | 220 | 169 | 2 | +0.000033 | +0.000177 |
| QQQ | 2019-2020 | 1 | bearish | 107 | 5 | +0.000860 | +0.000214 | -0.060746 | +0.043672 | 55 | 52 | 0 | +0.000191 | -0.000892 |
| QQQ | 2019-2020 | 1 | neutral | 7 | 6 | -0.004075 | -0.002041 | -0.023030 | +0.008758 | 3 | 4 | 0 | -0.004744 | -0.003147 |
| QQQ | 2019-2020 | 5 | all | 505 | 1 | +0.006601 | +0.008288 | -0.158172 | +0.106654 | 322 | 183 | 0 |  |  |
| QQQ | 2019-2020 | 5 | bullish | 391 | 5 | +0.004402 | +0.007626 | -0.158172 | +0.083723 | 250 | 141 | 0 | -0.002199 | -0.000662 |
| QQQ | 2019-2020 | 5 | bearish | 107 | 5 | +0.015546 | +0.016715 | -0.086331 | +0.106654 | 70 | 37 | 0 | +0.008945 | +0.008427 |
| QQQ | 2019-2020 | 5 | neutral | 7 | 6 | -0.007295 | -0.016706 | -0.019794 | +0.022915 | 2 | 5 | 0 | -0.013896 | -0.024994 |
| QQQ | 2019-2020 | 20 | all | 505 | 1 | +0.028637 | +0.039792 | -0.274946 | +0.244676 | 397 | 108 | 0 |  |  |
| QQQ | 2019-2020 | 20 | bullish | 391 | 5 | +0.020719 | +0.037712 | -0.274946 | +0.132769 | 301 | 90 | 0 | -0.007918 | -0.002079 |
| QQQ | 2019-2020 | 20 | bearish | 107 | 5 | +0.058071 | +0.051399 | -0.040393 | +0.244676 | 89 | 18 | 0 | +0.029434 | +0.011607 |
| QQQ | 2019-2020 | 20 | neutral | 7 | 6 | +0.021003 | +0.024207 | +0.001515 | +0.048415 | 7 | 0 | 0 | -0.007634 | -0.015584 |
| QQQ | 2021-2022 | 1 | all | 503 | 1 | -0.000036 | +0.000660 | -0.040090 | +0.067902 | 263 | 240 | 0 |  |  |
| QQQ | 2021-2022 | 1 | bullish | 271 | 7 | -0.000660 | +0.000458 | -0.040090 | +0.044581 | 142 | 129 | 0 | -0.000624 | -0.000203 |
| QQQ | 2021-2022 | 1 | bearish | 222 | 7 | +0.000848 | +0.001056 | -0.038569 | +0.067902 | 117 | 105 | 0 | +0.000884 | +0.000395 |
| QQQ | 2021-2022 | 1 | neutral | 10 | 9 | -0.002758 | -0.003708 | -0.018243 | +0.010376 | 4 | 6 | 0 | -0.002722 | -0.004368 |
| QQQ | 2021-2022 | 5 | all | 503 | 1 | -0.000870 | +0.000545 | -0.107232 | +0.091000 | 257 | 246 | 0 |  |  |
| QQQ | 2021-2022 | 5 | bullish | 271 | 7 | -0.004035 | -0.001130 | -0.090679 | +0.062992 | 127 | 144 | 0 | -0.003166 | -0.001675 |
| QQQ | 2021-2022 | 5 | bearish | 222 | 7 | +0.003457 | +0.006964 | -0.107232 | +0.091000 | 126 | 96 | 0 | +0.004327 | +0.006419 |
| QQQ | 2021-2022 | 5 | neutral | 10 | 9 | -0.011131 | -0.008399 | -0.073190 | +0.014812 | 4 | 6 | 0 | -0.010262 | -0.008944 |
| QQQ | 2021-2022 | 20 | all | 503 | 1 | -0.002782 | +0.001216 | -0.159595 | +0.151737 | 254 | 249 | 0 |  |  |
| QQQ | 2021-2022 | 20 | bullish | 271 | 7 | -0.019660 | -0.014371 | -0.159595 | +0.126635 | 115 | 156 | 0 | -0.016879 | -0.015587 |
| QQQ | 2021-2022 | 20 | bearish | 222 | 7 | +0.018234 | +0.027934 | -0.142223 | +0.151737 | 135 | 87 | 0 | +0.021016 | +0.026718 |
| QQQ | 2021-2022 | 20 | neutral | 10 | 9 | -0.011915 | -0.021567 | -0.133194 | +0.095332 | 4 | 6 | 0 | -0.009133 | -0.022784 |
| QQQ | 2023-2024 | 1 | all | 502 | 1 | +0.000611 | +0.001308 | -0.034906 | +0.029564 | 280 | 222 | 0 |  |  |
| QQQ | 2023-2024 | 1 | bullish | 368 | 4 | +0.000271 | +0.000595 | -0.034906 | +0.029564 | 198 | 170 | 0 | -0.000340 | -0.000713 |
| QQQ | 2023-2024 | 1 | bearish | 125 | 4 | +0.001719 | +0.003163 | -0.026249 | +0.025446 | 76 | 49 | 0 | +0.001108 | +0.001856 |
| QQQ | 2023-2024 | 1 | neutral | 9 | 6 | -0.000862 | +0.001554 | -0.030646 | +0.022112 | 6 | 3 | 0 | -0.001473 | +0.000246 |
| QQQ | 2023-2024 | 5 | all | 502 | 1 | +0.006171 | +0.006639 | -0.078409 | +0.067534 | 314 | 188 | 0 |  |  |
| QQQ | 2023-2024 | 5 | bullish | 368 | 4 | +0.003784 | +0.003350 | -0.078409 | +0.064974 | 221 | 147 | 0 | -0.002387 | -0.003289 |
| QQQ | 2023-2024 | 5 | bearish | 125 | 4 | +0.012158 | +0.014585 | -0.055469 | +0.067534 | 84 | 41 | 0 | +0.005988 | +0.007946 |
| QQQ | 2023-2024 | 5 | neutral | 9 | 6 | +0.020594 | +0.014657 | +0.006651 | +0.052546 | 9 | 0 | 0 | +0.014423 | +0.008017 |
| QQQ | 2023-2024 | 20 | all | 502 | 1 | +0.025069 | +0.026373 | -0.135766 | +0.180579 | 377 | 124 | 1 |  |  |
| QQQ | 2023-2024 | 20 | bullish | 368 | 4 | +0.021264 | +0.024101 | -0.135766 | +0.121400 | 276 | 91 | 1 | -0.003805 | -0.002273 |
| QQQ | 2023-2024 | 20 | bearish | 125 | 4 | +0.035725 | +0.036199 | -0.059266 | +0.180579 | 94 | 31 | 0 | +0.010656 | +0.009826 |
| QQQ | 2023-2024 | 20 | neutral | 9 | 6 | +0.032626 | +0.042626 | -0.039663 | +0.082553 | 7 | 2 | 0 | +0.007557 | +0.016252 |
| IWM | 2015-2016 | 1 | all | 504 | 1 | +0.000370 | +0.000797 | -0.038229 | +0.037771 | 271 | 232 | 1 |  |  |
| IWM | 2015-2016 | 1 | bullish | 326 | 6 | +0.000361 | +0.000813 | -0.024377 | +0.030549 | 178 | 147 | 1 | -0.000009 | +0.000016 |
| IWM | 2015-2016 | 1 | bearish | 162 | 5 | +0.000392 | +0.000799 | -0.038229 | +0.037771 | 85 | 77 | 0 | +0.000022 | +0.000001 |
| IWM | 2015-2016 | 1 | neutral | 16 | 9 | +0.000335 | +0.000335 | -0.015152 | +0.013203 | 8 | 8 | 0 | -0.000035 | -0.000462 |
| IWM | 2015-2016 | 5 | all | 504 | 1 | +0.001830 | +0.003833 | -0.089906 | +0.097138 | 284 | 219 | 1 |  |  |
| IWM | 2015-2016 | 5 | bullish | 326 | 6 | +0.001869 | +0.003169 | -0.057656 | +0.063800 | 184 | 141 | 1 | +0.000039 | -0.000664 |
| IWM | 2015-2016 | 5 | bearish | 162 | 5 | +0.001072 | +0.002323 | -0.089906 | +0.097138 | 87 | 75 | 0 | -0.000758 | -0.001511 |
| IWM | 2015-2016 | 5 | neutral | 16 | 9 | +0.008711 | +0.009251 | -0.024402 | +0.031777 | 13 | 3 | 0 | +0.006881 | +0.005418 |
| IWM | 2015-2016 | 20 | all | 504 | 1 | +0.006931 | +0.010016 | -0.133869 | +0.150915 | 291 | 213 | 0 |  |  |
| IWM | 2015-2016 | 20 | bullish | 326 | 6 | +0.003121 | +0.006614 | -0.128709 | +0.101687 | 176 | 150 | 0 | -0.003810 | -0.003403 |
| IWM | 2015-2016 | 20 | bearish | 162 | 5 | +0.014034 | +0.014485 | -0.133869 | +0.150915 | 104 | 58 | 0 | +0.007103 | +0.004469 |
| IWM | 2015-2016 | 20 | neutral | 16 | 9 | +0.012649 | +0.020494 | -0.115806 | +0.069341 | 11 | 5 | 0 | +0.005718 | +0.010478 |
| IWM | 2017-2018 | 1 | all | 502 | 1 | -0.000398 | +0.000165 | -0.040520 | +0.044742 | 255 | 244 | 3 |  |  |
| IWM | 2017-2018 | 1 | bullish | 341 | 7 | -0.000161 | +0.000439 | -0.032777 | +0.028585 | 177 | 162 | 2 | +0.000237 | +0.000274 |
| IWM | 2017-2018 | 1 | bearish | 132 | 5 | -0.001298 | -0.000284 | -0.040520 | +0.044742 | 63 | 68 | 1 | -0.000900 | -0.000449 |
| IWM | 2017-2018 | 1 | neutral | 29 | 11 | +0.000906 | +0.000059 | -0.010087 | +0.014074 | 15 | 14 | 0 | +0.001305 | -0.000105 |
| IWM | 2017-2018 | 5 | all | 502 | 1 | -0.000111 | +0.000517 | -0.089541 | +0.072331 | 258 | 243 | 1 |  |  |
| IWM | 2017-2018 | 5 | bullish | 341 | 7 | +0.000375 | +0.000759 | -0.068469 | +0.043697 | 175 | 166 | 0 | +0.000486 | +0.000242 |
| IWM | 2017-2018 | 5 | bearish | 132 | 5 | -0.002372 | -0.001069 | -0.089541 | +0.072331 | 63 | 68 | 1 | -0.002262 | -0.001586 |
| IWM | 2017-2018 | 5 | neutral | 29 | 11 | +0.004471 | +0.010059 | -0.062168 | +0.034000 | 20 | 9 | 0 | +0.004581 | +0.009541 |
| IWM | 2017-2018 | 20 | all | 502 | 1 | +0.002655 | +0.006580 | -0.156978 | +0.151964 | 301 | 200 | 1 |  |  |
| IWM | 2017-2018 | 20 | bullish | 341 | 7 | +0.002095 | +0.006798 | -0.133159 | +0.083583 | 208 | 132 | 1 | -0.000560 | +0.000218 |
| IWM | 2017-2018 | 20 | bearish | 132 | 5 | +0.003239 | +0.007669 | -0.156978 | +0.151964 | 75 | 57 | 0 | +0.000584 | +0.001089 |
| IWM | 2017-2018 | 20 | neutral | 29 | 11 | +0.006580 | +0.004880 | -0.062656 | +0.055617 | 18 | 11 | 0 | +0.003925 | -0.001700 |
| IWM | 2019-2020 | 1 | all | 505 | 1 | -0.000196 | +0.000389 | -0.046032 | +0.057848 | 259 | 243 | 3 |  |  |
| IWM | 2019-2020 | 1 | bullish | 342 | 7 | -0.000143 | +0.000604 | -0.041820 | +0.057848 | 179 | 160 | 3 | +0.000053 | +0.000215 |
| IWM | 2019-2020 | 1 | bearish | 146 | 6 | +0.000297 | +0.000846 | -0.046032 | +0.047248 | 76 | 70 | 0 | +0.000493 | +0.000457 |
| IWM | 2019-2020 | 1 | neutral | 17 | 10 | -0.005498 | -0.004164 | -0.038211 | +0.020706 | 4 | 13 | 0 | -0.005303 | -0.004553 |
| IWM | 2019-2020 | 5 | all | 505 | 1 | +0.003653 | +0.005608 | -0.230792 | +0.160709 | 298 | 207 | 0 |  |  |
| IWM | 2019-2020 | 5 | bullish | 342 | 7 | +0.003612 | +0.004374 | -0.113530 | +0.116946 | 197 | 145 | 0 | -0.000041 | -0.001235 |
| IWM | 2019-2020 | 5 | bearish | 146 | 6 | +0.004906 | +0.009641 | -0.230792 | +0.160709 | 92 | 54 | 0 | +0.001253 | +0.004032 |
| IWM | 2019-2020 | 5 | neutral | 17 | 10 | -0.006293 | +0.001167 | -0.095947 | +0.060931 | 9 | 8 | 0 | -0.009945 | -0.004442 |
| IWM | 2019-2020 | 20 | all | 505 | 1 | +0.018300 | +0.024820 | -0.404586 | +0.246182 | 345 | 160 | 0 |  |  |
| IWM | 2019-2020 | 20 | bullish | 342 | 7 | +0.015769 | +0.017142 | -0.404586 | +0.201741 | 225 | 117 | 0 | -0.002530 | -0.007678 |
| IWM | 2019-2020 | 20 | bearish | 146 | 6 | +0.030245 | +0.041190 | -0.305699 | +0.246182 | 113 | 33 | 0 | +0.011945 | +0.016371 |
| IWM | 2019-2020 | 20 | neutral | 17 | 10 | -0.033381 | -0.007154 | -0.385306 | +0.130298 | 7 | 10 | 0 | -0.051681 | -0.031974 |
| IWM | 2021-2022 | 1 | all | 503 | 1 | -0.000521 | -0.000269 | -0.044406 | +0.051614 | 245 | 258 | 0 |  |  |
| IWM | 2021-2022 | 1 | bullish | 244 | 8 | -0.000948 | -0.000264 | -0.044406 | +0.034967 | 119 | 125 | 0 | -0.000426 | +0.000005 |
| IWM | 2021-2022 | 1 | bearish | 245 | 8 | +0.000202 | -0.000180 | -0.034329 | +0.051614 | 121 | 124 | 0 | +0.000723 | +0.000090 |
| IWM | 2021-2022 | 1 | neutral | 14 | 12 | -0.005736 | -0.007015 | -0.023814 | +0.014132 | 5 | 9 | 0 | -0.005215 | -0.006745 |
| IWM | 2021-2022 | 5 | all | 503 | 1 | -0.001259 | -0.001305 | -0.109278 | +0.084537 | 245 | 258 | 0 |  |  |
| IWM | 2021-2022 | 5 | bullish | 244 | 8 | -0.005531 | -0.007624 | -0.084561 | +0.074836 | 96 | 148 | 0 | -0.004271 | -0.006319 |
| IWM | 2021-2022 | 5 | bearish | 245 | 8 | +0.003136 | +0.006837 | -0.109278 | +0.084537 | 144 | 101 | 0 | +0.004395 | +0.008142 |
| IWM | 2021-2022 | 5 | neutral | 14 | 12 | -0.003734 | -0.006130 | -0.040594 | +0.053652 | 5 | 9 | 0 | -0.002475 | -0.004825 |
| IWM | 2021-2022 | 20 | all | 503 | 1 | -0.003887 | -0.002359 | -0.143493 | +0.159711 | 245 | 258 | 0 |  |  |
| IWM | 2021-2022 | 20 | bullish | 244 | 8 | -0.019388 | -0.018595 | -0.143493 | +0.108343 | 94 | 150 | 0 | -0.015501 | -0.016236 |
| IWM | 2021-2022 | 20 | bearish | 245 | 8 | +0.011501 | +0.012019 | -0.140935 | +0.159711 | 146 | 99 | 0 | +0.015388 | +0.014379 |
| IWM | 2021-2022 | 20 | neutral | 14 | 12 | -0.003019 | -0.018381 | -0.073367 | +0.075075 | 5 | 9 | 0 | +0.000868 | -0.016022 |
| IWM | 2023-2024 | 1 | all | 502 | 1 | -0.000154 | +0.000083 | -0.049087 | +0.033298 | 252 | 250 | 0 |  |  |
| IWM | 2023-2024 | 1 | bullish | 327 | 6 | -0.000305 | -0.000230 | -0.049087 | +0.033298 | 161 | 166 | 0 | -0.000151 | -0.000312 |
| IWM | 2023-2024 | 1 | bearish | 165 | 5 | +0.000137 | +0.000456 | -0.027646 | +0.026302 | 86 | 79 | 0 | +0.000291 | +0.000374 |
| IWM | 2023-2024 | 1 | neutral | 10 | 9 | -0.000012 | +0.000595 | -0.009268 | +0.008512 | 5 | 5 | 0 | +0.000143 | +0.000512 |
| IWM | 2023-2024 | 5 | all | 502 | 1 | +0.002091 | +0.000601 | -0.097377 | +0.110287 | 258 | 244 | 0 |  |  |
| IWM | 2023-2024 | 5 | bullish | 327 | 6 | +0.000177 | +0.000298 | -0.097377 | +0.101942 | 164 | 163 | 0 | -0.001914 | -0.000302 |
| IWM | 2023-2024 | 5 | bearish | 165 | 5 | +0.005623 | +0.001765 | -0.044079 | +0.110287 | 88 | 77 | 0 | +0.003532 | +0.001164 |
| IWM | 2023-2024 | 5 | neutral | 10 | 9 | +0.006424 | +0.003598 | -0.053753 | +0.055006 | 6 | 4 | 0 | +0.004333 | +0.002997 |
| IWM | 2023-2024 | 20 | all | 502 | 1 | +0.008755 | +0.007829 | -0.107619 | +0.143097 | 280 | 222 | 0 |  |  |
| IWM | 2023-2024 | 20 | bullish | 327 | 6 | +0.002886 | +0.003330 | -0.107619 | +0.140741 | 173 | 154 | 0 | -0.005869 | -0.004499 |
| IWM | 2023-2024 | 20 | bearish | 165 | 5 | +0.018696 | +0.015421 | -0.085106 | +0.135919 | 100 | 65 | 0 | +0.009942 | +0.007593 |
| IWM | 2023-2024 | 20 | neutral | 10 | 9 | +0.036638 | +0.025589 | -0.064715 | +0.143097 | 7 | 3 | 0 | +0.027884 | +0.017760 |
| TLT | 2015-2016 | 1 | all | 504 | 1 | -0.000099 | +0.000115 | -0.020830 | +0.015824 | 254 | 248 | 2 |  |  |
| TLT | 2015-2016 | 1 | bullish | 258 | 7 | -0.000242 | -0.000073 | -0.018269 | +0.015824 | 126 | 131 | 1 | -0.000143 | -0.000188 |
| TLT | 2015-2016 | 1 | bearish | 216 | 8 | -0.000118 | +0.000167 | -0.020830 | +0.013406 | 109 | 106 | 1 | -0.000019 | +0.000052 |
| TLT | 2015-2016 | 1 | neutral | 30 | 12 | +0.001263 | +0.001231 | -0.003798 | +0.008296 | 19 | 11 | 0 | +0.001362 | +0.001117 |
| TLT | 2015-2016 | 5 | all | 504 | 1 | -0.000546 | +0.000506 | -0.074111 | +0.045586 | 261 | 242 | 1 |  |  |
| TLT | 2015-2016 | 5 | bullish | 258 | 7 | +0.000009 | +0.001076 | -0.046372 | +0.045586 | 137 | 121 | 0 | +0.000555 | +0.000570 |
| TLT | 2015-2016 | 5 | bearish | 216 | 8 | -0.001172 | +0.000413 | -0.074111 | +0.038594 | 110 | 105 | 1 | -0.000626 | -0.000093 |
| TLT | 2015-2016 | 5 | neutral | 30 | 12 | -0.000817 | -0.001475 | -0.020302 | +0.017951 | 14 | 16 | 0 | -0.000271 | -0.001982 |
| TLT | 2015-2016 | 20 | all | 504 | 1 | -0.003200 | +0.001017 | -0.094146 | +0.078670 | 256 | 248 | 0 |  |  |
| TLT | 2015-2016 | 20 | bullish | 258 | 7 | -0.000468 | +0.002643 | -0.091340 | +0.078670 | 142 | 116 | 0 | +0.002732 | +0.001627 |
| TLT | 2015-2016 | 20 | bearish | 216 | 8 | -0.007489 | -0.008306 | -0.094146 | +0.077563 | 97 | 119 | 0 | -0.004289 | -0.009323 |
| TLT | 2015-2016 | 20 | neutral | 30 | 12 | +0.004184 | +0.009504 | -0.063807 | +0.045970 | 17 | 13 | 0 | +0.007384 | +0.008488 |
| TLT | 2017-2018 | 1 | all | 502 | 1 | +0.000228 | +0.000161 | -0.014533 | +0.012923 | 258 | 238 | 6 |  |  |
| TLT | 2017-2018 | 1 | bullish | 236 | 7 | +0.000084 | +0.000083 | -0.010409 | +0.008908 | 120 | 110 | 6 | -0.000144 | -0.000078 |
| TLT | 2017-2018 | 1 | bearish | 237 | 8 | +0.000449 | +0.000322 | -0.014533 | +0.012923 | 126 | 111 | 0 | +0.000221 | +0.000161 |
| TLT | 2017-2018 | 1 | neutral | 29 | 13 | -0.000402 | -0.001429 | -0.009274 | +0.008061 | 12 | 17 | 0 | -0.000630 | -0.001590 |
| TLT | 2017-2018 | 5 | all | 502 | 1 | +0.000360 | +0.000418 | -0.034370 | +0.042203 | 255 | 246 | 1 |  |  |
| TLT | 2017-2018 | 5 | bullish | 236 | 7 | -0.000771 | -0.000531 | -0.027537 | +0.027333 | 116 | 120 | 0 | -0.001132 | -0.000949 |
| TLT | 2017-2018 | 5 | bearish | 237 | 8 | +0.001690 | +0.002159 | -0.034370 | +0.042203 | 128 | 108 | 1 | +0.001329 | +0.001740 |
| TLT | 2017-2018 | 5 | neutral | 29 | 13 | -0.001296 | -0.001760 | -0.022876 | +0.016774 | 11 | 18 | 0 | -0.001657 | -0.002178 |
| TLT | 2017-2018 | 20 | all | 502 | 1 | +0.000533 | +0.000976 | -0.053913 | +0.065138 | 260 | 242 | 0 |  |  |
| TLT | 2017-2018 | 20 | bullish | 236 | 7 | -0.003449 | -0.006770 | -0.049972 | +0.042698 | 95 | 141 | 0 | -0.003982 | -0.007746 |
| TLT | 2017-2018 | 20 | bearish | 237 | 8 | +0.006300 | +0.008611 | -0.053607 | +0.065138 | 156 | 81 | 0 | +0.005768 | +0.007635 |
| TLT | 2017-2018 | 20 | neutral | 29 | 13 | -0.014194 | -0.019586 | -0.053913 | +0.034430 | 9 | 20 | 0 | -0.014727 | -0.020562 |
| TLT | 2019-2020 | 1 | all | 505 | 1 | -0.000097 | +0.000082 | -0.064343 | +0.053968 | 257 | 245 | 3 |  |  |
| TLT | 2019-2020 | 1 | bullish | 300 | 5 | -0.000450 | -0.000064 | -0.064343 | +0.053968 | 146 | 151 | 3 | -0.000353 | -0.000146 |
| TLT | 2019-2020 | 1 | bearish | 182 | 4 | +0.000287 | +0.000185 | -0.012501 | +0.015243 | 95 | 87 | 0 | +0.000384 | +0.000103 |
| TLT | 2019-2020 | 1 | neutral | 23 | 8 | +0.001468 | +0.002362 | -0.009646 | +0.008338 | 16 | 7 | 0 | +0.001565 | +0.002280 |
| TLT | 2019-2020 | 5 | all | 505 | 1 | +0.001886 | +0.001520 | -0.140480 | +0.113647 | 283 | 221 | 1 |  |  |
| TLT | 2019-2020 | 5 | bullish | 300 | 5 | +0.002953 | +0.002559 | -0.140480 | +0.113647 | 176 | 123 | 1 | +0.001066 | +0.001039 |
| TLT | 2019-2020 | 5 | bearish | 182 | 4 | -0.000494 | +0.000119 | -0.040089 | +0.059957 | 91 | 91 | 0 | -0.002380 | -0.001401 |
| TLT | 2019-2020 | 5 | neutral | 23 | 8 | +0.006808 | +0.007734 | -0.021672 | +0.032786 | 16 | 7 | 0 | +0.004922 | +0.006214 |
| TLT | 2019-2020 | 20 | all | 505 | 1 | +0.009335 | +0.002346 | -0.065179 | +0.180496 | 267 | 238 | 0 |  |  |
| TLT | 2019-2020 | 20 | bullish | 300 | 5 | +0.014484 | +0.003689 | -0.065179 | +0.180496 | 164 | 136 | 0 | +0.005150 | +0.001343 |
| TLT | 2019-2020 | 20 | bearish | 182 | 4 | -0.000264 | -0.005069 | -0.051522 | +0.061302 | 83 | 99 | 0 | -0.009598 | -0.007415 |
| TLT | 2019-2020 | 20 | neutral | 23 | 8 | +0.018118 | +0.018879 | -0.028277 | +0.049840 | 20 | 3 | 0 | +0.008784 | +0.016533 |
| TLT | 2021-2022 | 1 | all | 503 | 1 | +0.000088 | +0.000359 | -0.024099 | +0.030152 | 263 | 238 | 2 |  |  |
| TLT | 2021-2022 | 1 | bullish | 169 | 5 | -0.000103 | +0.000096 | -0.022056 | +0.018605 | 86 | 82 | 1 | -0.000191 | -0.000263 |
| TLT | 2021-2022 | 1 | bearish | 321 | 5 | +0.000117 | +0.000403 | -0.024099 | +0.030152 | 170 | 151 | 0 | +0.000029 | +0.000043 |
| TLT | 2021-2022 | 1 | neutral | 13 | 9 | +0.001841 | +0.000939 | -0.011610 | +0.016999 | 7 | 5 | 1 | +0.001754 | +0.000579 |
| TLT | 2021-2022 | 5 | all | 503 | 1 | -0.002776 | -0.002440 | -0.061638 | +0.061270 | 236 | 267 | 0 |  |  |
| TLT | 2021-2022 | 5 | bullish | 169 | 5 | -0.002401 | +0.000601 | -0.045450 | +0.053169 | 85 | 84 | 0 | +0.000375 | +0.003041 |
| TLT | 2021-2022 | 5 | bearish | 321 | 5 | -0.003232 | -0.004727 | -0.061638 | +0.061270 | 142 | 179 | 0 | -0.000455 | -0.002286 |
| TLT | 2021-2022 | 5 | neutral | 13 | 9 | +0.003588 | +0.005130 | -0.045551 | +0.036752 | 9 | 4 | 0 | +0.006365 | +0.007570 |
| TLT | 2021-2022 | 20 | all | 503 | 1 | -0.012513 | -0.014320 | -0.115699 | +0.166809 | 201 | 302 | 0 |  |  |
| TLT | 2021-2022 | 20 | bullish | 169 | 5 | -0.009710 | -0.009430 | -0.086979 | +0.069559 | 71 | 98 | 0 | +0.002803 | +0.004891 |
| TLT | 2021-2022 | 20 | bearish | 321 | 5 | -0.014434 | -0.018371 | -0.115699 | +0.166809 | 122 | 199 | 0 | -0.001922 | -0.004051 |
| TLT | 2021-2022 | 20 | neutral | 13 | 9 | -0.001497 | +0.002072 | -0.103623 | +0.040995 | 8 | 5 | 0 | +0.011016 | +0.016392 |
| TLT | 2023-2024 | 1 | all | 502 | 1 | +0.000303 | +0.000115 | -0.022487 | +0.024148 | 255 | 244 | 3 |  |  |
| TLT | 2023-2024 | 1 | bullish | 198 | 5 | +0.000957 | +0.001173 | -0.020804 | +0.024148 | 112 | 84 | 2 | +0.000654 | +0.001058 |
| TLT | 2023-2024 | 1 | bearish | 287 | 6 | -0.000286 | -0.000451 | -0.022487 | +0.017268 | 133 | 153 | 1 | -0.000589 | -0.000567 |
| TLT | 2023-2024 | 1 | neutral | 17 | 10 | +0.002631 | +0.002353 | -0.007486 | +0.010591 | 10 | 7 | 0 | +0.002328 | +0.002238 |
| TLT | 2023-2024 | 5 | all | 502 | 1 | -0.001006 | -0.001293 | -0.055137 | +0.054675 | 239 | 263 | 0 |  |  |
| TLT | 2023-2024 | 5 | bullish | 198 | 5 | +0.000895 | -0.000197 | -0.044222 | +0.054675 | 98 | 100 | 0 | +0.001901 | +0.001096 |
| TLT | 2023-2024 | 5 | bearish | 287 | 6 | -0.002244 | -0.002172 | -0.055137 | +0.047834 | 134 | 153 | 0 | -0.001238 | -0.000879 |
| TLT | 2023-2024 | 5 | neutral | 17 | 10 | -0.002239 | -0.002839 | -0.025831 | +0.030185 | 7 | 10 | 0 | -0.001234 | -0.001546 |
| TLT | 2023-2024 | 20 | all | 502 | 1 | -0.006346 | -0.007974 | -0.095972 | +0.109071 | 215 | 287 | 0 |  |  |
| TLT | 2023-2024 | 20 | bullish | 198 | 5 | -0.007046 | -0.013355 | -0.086669 | +0.091195 | 77 | 121 | 0 | -0.000700 | -0.005380 |
| TLT | 2023-2024 | 20 | bearish | 287 | 6 | -0.005627 | -0.005031 | -0.095972 | +0.109071 | 133 | 154 | 0 | +0.000718 | +0.002944 |
| TLT | 2023-2024 | 20 | neutral | 17 | 10 | -0.010319 | -0.015086 | -0.071013 | +0.098002 | 5 | 12 | 0 | -0.003973 | -0.007112 |
| GLD | 2015-2016 | 1 | all | 504 | 1 | -0.000231 | -0.000337 | -0.022290 | +0.026997 | 232 | 270 | 2 |  |  |
| GLD | 2015-2016 | 1 | bullish | 247 | 6 | +0.000240 | +0.000156 | -0.019955 | +0.026997 | 125 | 122 | 0 | +0.000471 | +0.000493 |
| GLD | 2015-2016 | 1 | bearish | 238 | 6 | -0.000680 | -0.000599 | -0.022290 | +0.018490 | 100 | 136 | 2 | -0.000449 | -0.000263 |
| GLD | 2015-2016 | 1 | neutral | 19 | 10 | -0.000734 | -0.000744 | -0.008868 | +0.009965 | 7 | 12 | 0 | -0.000503 | -0.000407 |
| GLD | 2015-2016 | 5 | all | 504 | 1 | -0.000351 | -0.002281 | -0.057763 | +0.084434 | 231 | 272 | 1 |  |  |
| GLD | 2015-2016 | 5 | bullish | 247 | 6 | +0.001663 | -0.000785 | -0.050586 | +0.084434 | 121 | 126 | 0 | +0.002014 | +0.001496 |
| GLD | 2015-2016 | 5 | bearish | 238 | 6 | -0.002235 | -0.003254 | -0.057763 | +0.046640 | 101 | 136 | 1 | -0.001884 | -0.000973 |
| GLD | 2015-2016 | 5 | neutral | 19 | 10 | -0.002925 | -0.002940 | -0.039828 | +0.034937 | 9 | 10 | 0 | -0.002574 | -0.000659 |
| GLD | 2015-2016 | 20 | all | 504 | 1 | -0.001428 | -0.002064 | -0.100322 | +0.147566 | 240 | 264 | 0 |  |  |
| GLD | 2015-2016 | 20 | bullish | 247 | 6 | +0.000107 | -0.001762 | -0.089259 | +0.126679 | 117 | 130 | 0 | +0.001534 | +0.000302 |
| GLD | 2015-2016 | 20 | bearish | 238 | 6 | -0.003471 | -0.001847 | -0.100322 | +0.147566 | 116 | 122 | 0 | -0.002043 | +0.000217 |
| GLD | 2015-2016 | 20 | neutral | 19 | 10 | +0.004218 | -0.008851 | -0.047782 | +0.128098 | 7 | 12 | 0 | +0.005646 | -0.006787 |
| GLD | 2017-2018 | 1 | all | 502 | 1 | +0.000053 | -0.000085 | -0.013908 | +0.017149 | 244 | 255 | 3 |  |  |
| GLD | 2017-2018 | 1 | bullish | 247 | 6 | +0.000127 | +0.000000 | -0.013908 | +0.017149 | 122 | 122 | 3 | +0.000074 | +0.000085 |
| GLD | 2017-2018 | 1 | bearish | 230 | 7 | -0.000048 | -0.000332 | -0.009411 | +0.013835 | 107 | 123 | 0 | -0.000100 | -0.000247 |
| GLD | 2017-2018 | 1 | neutral | 25 | 12 | +0.000242 | +0.000250 | -0.008015 | +0.005375 | 15 | 10 | 0 | +0.000189 | +0.000335 |
| GLD | 2017-2018 | 5 | all | 502 | 1 | +0.000801 | +0.000166 | -0.033299 | +0.037186 | 254 | 245 | 3 |  |  |
| GLD | 2017-2018 | 5 | bullish | 247 | 6 | +0.000884 | +0.000395 | -0.029500 | +0.037186 | 125 | 121 | 1 | +0.000083 | +0.000229 |
| GLD | 2017-2018 | 5 | bearish | 230 | 7 | +0.001089 | +0.000370 | -0.033299 | +0.032304 | 119 | 109 | 2 | +0.000289 | +0.000205 |
| GLD | 2017-2018 | 5 | neutral | 25 | 12 | -0.002681 | -0.000947 | -0.022039 | +0.021528 | 10 | 15 | 0 | -0.003482 | -0.001113 |
| GLD | 2017-2018 | 20 | all | 502 | 1 | +0.003046 | -0.000040 | -0.059980 | +0.065995 | 250 | 251 | 1 |  |  |
| GLD | 2017-2018 | 20 | bullish | 247 | 6 | +0.003588 | +0.000792 | -0.059980 | +0.060373 | 128 | 119 | 0 | +0.000542 | +0.000832 |
| GLD | 2017-2018 | 20 | bearish | 230 | 7 | +0.001465 | -0.003857 | -0.056869 | +0.065995 | 105 | 124 | 1 | -0.001582 | -0.003818 |
| GLD | 2017-2018 | 20 | neutral | 25 | 12 | +0.012244 | +0.011606 | -0.043002 | +0.057558 | 17 | 8 | 0 | +0.009197 | +0.011645 |
| GLD | 2019-2020 | 1 | all | 505 | 1 | +0.000004 | +0.000323 | -0.041092 | +0.030131 | 264 | 240 | 1 |  |  |
| GLD | 2019-2020 | 1 | bullish | 314 | 5 | -0.000008 | +0.000260 | -0.041092 | +0.030131 | 164 | 149 | 1 | -0.000012 | -0.000063 |
| GLD | 2019-2020 | 1 | bearish | 181 | 4 | +0.000075 | +0.000499 | -0.016391 | +0.017644 | 96 | 85 | 0 | +0.000071 | +0.000177 |
| GLD | 2019-2020 | 1 | neutral | 10 | 6 | -0.000900 | -0.000774 | -0.005627 | +0.008435 | 4 | 6 | 0 | -0.000904 | -0.001097 |
| GLD | 2019-2020 | 5 | all | 505 | 1 | +0.003285 | +0.003539 | -0.096595 | +0.089048 | 305 | 198 | 2 |  |  |
| GLD | 2019-2020 | 5 | bullish | 314 | 5 | +0.003792 | +0.004376 | -0.096595 | +0.089048 | 197 | 116 | 1 | +0.000507 | +0.000837 |
| GLD | 2019-2020 | 5 | bearish | 181 | 4 | +0.002268 | +0.001487 | -0.048144 | +0.047319 | 104 | 76 | 1 | -0.001017 | -0.002052 |
| GLD | 2019-2020 | 5 | neutral | 10 | 6 | +0.005762 | -0.006449 | -0.017938 | +0.052901 | 4 | 6 | 0 | +0.002478 | -0.009988 |
| GLD | 2019-2020 | 20 | all | 505 | 1 | +0.014268 | +0.006860 | -0.116025 | +0.173379 | 286 | 217 | 2 |  |  |
| GLD | 2019-2020 | 20 | bullish | 314 | 5 | +0.017162 | +0.009565 | -0.116025 | +0.173379 | 185 | 127 | 2 | +0.002893 | +0.002706 |
| GLD | 2019-2020 | 20 | bearish | 181 | 4 | +0.008644 | +0.002499 | -0.060750 | +0.108775 | 94 | 87 | 0 | -0.005625 | -0.004361 |
| GLD | 2019-2020 | 20 | neutral | 10 | 6 | +0.025234 | +0.035855 | -0.032808 | +0.091296 | 7 | 3 | 0 | +0.010965 | +0.028995 |
| GLD | 2021-2022 | 1 | all | 503 | 1 | -0.000009 | -0.000115 | -0.029848 | +0.022181 | 247 | 253 | 3 |  |  |
| GLD | 2021-2022 | 1 | bullish | 196 | 6 | -0.000014 | -0.000120 | -0.029848 | +0.017921 | 95 | 100 | 1 | -0.000005 | -0.000005 |
| GLD | 2021-2022 | 1 | bearish | 280 | 6 | +0.000001 | +0.000089 | -0.019333 | +0.022181 | 141 | 138 | 1 | +0.000010 | +0.000204 |
| GLD | 2021-2022 | 1 | neutral | 27 | 12 | -0.000073 | -0.000565 | -0.008337 | +0.009918 | 11 | 15 | 1 | -0.000064 | -0.000450 |
| GLD | 2021-2022 | 5 | all | 503 | 1 | -0.000123 | +0.001745 | -0.059434 | +0.063177 | 267 | 236 | 0 |  |  |
| GLD | 2021-2022 | 5 | bullish | 196 | 6 | +0.000558 | +0.002484 | -0.059434 | +0.063177 | 107 | 89 | 0 | +0.000680 | +0.000739 |
| GLD | 2021-2022 | 5 | bearish | 280 | 6 | -0.000166 | +0.001434 | -0.055523 | +0.057247 | 149 | 131 | 0 | -0.000043 | -0.000312 |
| GLD | 2021-2022 | 5 | neutral | 27 | 12 | -0.004612 | -0.006026 | -0.053973 | +0.035986 | 11 | 16 | 0 | -0.004489 | -0.007771 |
| GLD | 2021-2022 | 20 | all | 503 | 1 | +0.001321 | +0.002315 | -0.092283 | +0.125867 | 262 | 240 | 1 |  |  |
| GLD | 2021-2022 | 20 | bullish | 196 | 6 | +0.002518 | +0.006403 | -0.092283 | +0.125867 | 105 | 91 | 0 | +0.001197 | +0.004088 |
| GLD | 2021-2022 | 20 | bearish | 280 | 6 | +0.001201 | +0.001820 | -0.084254 | +0.113736 | 145 | 134 | 1 | -0.000121 | -0.000495 |
| GLD | 2021-2022 | 20 | neutral | 27 | 12 | -0.006117 | -0.004649 | -0.061979 | +0.056472 | 12 | 15 | 0 | -0.007438 | -0.006964 |
| GLD | 2023-2024 | 1 | all | 502 | 1 | +0.000057 | -0.000054 | -0.022446 | +0.020727 | 243 | 255 | 4 |  |  |
| GLD | 2023-2024 | 1 | bullish | 321 | 6 | +0.000023 | -0.000279 | -0.022446 | +0.020727 | 150 | 169 | 2 | -0.000034 | -0.000224 |
| GLD | 2023-2024 | 1 | bearish | 170 | 6 | +0.000086 | +0.000115 | -0.017695 | +0.016851 | 87 | 81 | 2 | +0.000029 | +0.000169 |
| GLD | 2023-2024 | 1 | neutral | 11 | 8 | +0.000589 | +0.001970 | -0.006968 | +0.005925 | 6 | 5 | 0 | +0.000532 | +0.002024 |
| GLD | 2023-2024 | 5 | all | 502 | 1 | +0.002960 | +0.001381 | -0.048420 | +0.051503 | 264 | 238 | 0 |  |  |
| GLD | 2023-2024 | 5 | bullish | 321 | 6 | +0.001854 | +0.000221 | -0.048420 | +0.051503 | 162 | 159 | 0 | -0.001106 | -0.001160 |
| GLD | 2023-2024 | 5 | bearish | 170 | 6 | +0.005309 | +0.003434 | -0.040604 | +0.050823 | 97 | 73 | 0 | +0.002348 | +0.002053 |
| GLD | 2023-2024 | 5 | neutral | 11 | 8 | -0.001051 | -0.002944 | -0.014551 | +0.016827 | 5 | 6 | 0 | -0.004011 | -0.004326 |
| GLD | 2023-2024 | 20 | all | 502 | 1 | +0.013891 | +0.010051 | -0.063900 | +0.114880 | 312 | 189 | 1 |  |  |
| GLD | 2023-2024 | 20 | bullish | 321 | 6 | +0.009524 | +0.005999 | -0.063900 | +0.108206 | 183 | 137 | 1 | -0.004367 | -0.004051 |
| GLD | 2023-2024 | 20 | bearish | 170 | 6 | +0.021998 | +0.017896 | -0.053979 | +0.114880 | 122 | 48 | 0 | +0.008107 | +0.007846 |
| GLD | 2023-2024 | 20 | neutral | 11 | 8 | +0.016058 | +0.003625 | -0.031289 | +0.078031 | 7 | 4 | 0 | +0.002167 | -0.006425 |

### momentum_in_trend_context

| symbol | segment | h | state | n | episodes | mean | median | min | max | pos | neg | zero | mean delta | median delta |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SPY | 2015-2016 | 1 | all | 504 | 1 | +0.000303 | +0.000444 | -0.041754 | +0.027560 | 265 | 235 | 4 |  |  |
| SPY | 2015-2016 | 1 | bullish | 162 | 25 | +0.000197 | +0.000537 | -0.017007 | +0.013904 | 85 | 76 | 1 | -0.000107 | +0.000093 |
| SPY | 2015-2016 | 1 | bearish | 78 | 18 | +0.000154 | -0.000048 | -0.041754 | +0.027560 | 39 | 39 | 0 | -0.000149 | -0.000493 |
| SPY | 2015-2016 | 1 | neutral | 264 | 44 | +0.000413 | +0.000482 | -0.022727 | +0.019503 | 141 | 120 | 3 | +0.000109 | +0.000038 |
| SPY | 2015-2016 | 5 | all | 504 | 1 | +0.001341 | +0.002023 | -0.104357 | +0.062883 | 285 | 218 | 1 |  |  |
| SPY | 2015-2016 | 5 | bullish | 162 | 25 | -0.000551 | -0.000898 | -0.035129 | +0.028729 | 76 | 86 | 0 | -0.001892 | -0.002921 |
| SPY | 2015-2016 | 5 | bearish | 78 | 18 | +0.007389 | +0.007568 | -0.046127 | +0.062883 | 50 | 28 | 0 | +0.006048 | +0.005545 |
| SPY | 2015-2016 | 5 | neutral | 264 | 44 | +0.000715 | +0.003067 | -0.104357 | +0.041322 | 159 | 104 | 1 | -0.000626 | +0.001044 |
| SPY | 2015-2016 | 20 | all | 504 | 1 | +0.005167 | +0.006208 | -0.106024 | +0.100437 | 303 | 201 | 0 |  |  |
| SPY | 2015-2016 | 20 | bullish | 162 | 25 | -0.000193 | +0.001104 | -0.052052 | +0.066837 | 87 | 75 | 0 | -0.005360 | -0.005105 |
| SPY | 2015-2016 | 20 | bearish | 78 | 18 | +0.020517 | +0.020295 | -0.088022 | +0.100437 | 56 | 22 | 0 | +0.015350 | +0.014086 |
| SPY | 2015-2016 | 20 | neutral | 264 | 44 | +0.003921 | +0.008243 | -0.106024 | +0.075789 | 160 | 104 | 0 | -0.001246 | +0.002035 |
| SPY | 2017-2018 | 1 | all | 502 | 1 | -0.000196 | +0.000143 | -0.038730 | +0.043268 | 261 | 235 | 6 |  |  |
| SPY | 2017-2018 | 1 | bullish | 282 | 22 | +0.000227 | +0.000226 | -0.017744 | +0.010738 | 150 | 127 | 5 | +0.000423 | +0.000083 |
| SPY | 2017-2018 | 1 | bearish | 56 | 13 | -0.000607 | -0.000019 | -0.029305 | +0.043268 | 28 | 28 | 0 | -0.000410 | -0.000162 |
| SPY | 2017-2018 | 1 | neutral | 164 | 34 | -0.000783 | +0.000074 | -0.038730 | +0.035354 | 83 | 80 | 1 | -0.000587 | -0.000069 |
| SPY | 2017-2018 | 5 | all | 502 | 1 | +0.000777 | +0.002563 | -0.088880 | +0.060219 | 305 | 195 | 2 |  |  |
| SPY | 2017-2018 | 5 | bullish | 282 | 22 | +0.001964 | +0.002609 | -0.080156 | +0.024777 | 184 | 96 | 2 | +0.001187 | +0.000046 |
| SPY | 2017-2018 | 5 | bearish | 56 | 13 | -0.000566 | +0.007317 | -0.088880 | +0.060219 | 32 | 24 | 0 | -0.001343 | +0.004754 |
| SPY | 2017-2018 | 5 | neutral | 164 | 34 | -0.000805 | +0.002057 | -0.060478 | +0.046894 | 89 | 75 | 0 | -0.001582 | -0.000506 |
| SPY | 2017-2018 | 20 | all | 502 | 1 | +0.005422 | +0.013065 | -0.122714 | +0.116879 | 340 | 162 | 0 |  |  |
| SPY | 2017-2018 | 20 | bullish | 282 | 22 | +0.006762 | +0.012655 | -0.095006 | +0.069767 | 191 | 91 | 0 | +0.001340 | -0.000410 |
| SPY | 2017-2018 | 20 | bearish | 56 | 13 | +0.003090 | +0.005397 | -0.118293 | +0.116879 | 30 | 26 | 0 | -0.002332 | -0.007668 |
| SPY | 2017-2018 | 20 | neutral | 164 | 34 | +0.003914 | +0.014727 | -0.122714 | +0.069287 | 119 | 45 | 0 | -0.001508 | +0.001662 |
| SPY | 2019-2020 | 1 | all | 505 | 1 | +0.000304 | +0.000804 | -0.056612 | +0.046810 | 284 | 218 | 3 |  |  |
| SPY | 2019-2020 | 1 | bullish | 278 | 19 | -0.000078 | +0.000826 | -0.034836 | +0.017938 | 159 | 119 | 0 | -0.000382 | +0.000022 |
| SPY | 2019-2020 | 1 | bearish | 31 | 8 | +0.005383 | +0.007841 | -0.056612 | +0.046810 | 19 | 12 | 0 | +0.005079 | +0.007037 |
| SPY | 2019-2020 | 1 | neutral | 196 | 26 | +0.000043 | +0.000601 | -0.034852 | +0.036484 | 106 | 87 | 3 | -0.000261 | -0.000203 |
| SPY | 2019-2020 | 5 | all | 505 | 1 | +0.003847 | +0.006416 | -0.157357 | +0.117623 | 331 | 174 | 0 |  |  |
| SPY | 2019-2020 | 5 | bullish | 278 | 19 | +0.002682 | +0.005418 | -0.113155 | +0.054314 | 192 | 86 | 0 | -0.001164 | -0.000998 |
| SPY | 2019-2020 | 5 | bearish | 31 | 8 | +0.003128 | +0.023271 | -0.157357 | +0.117623 | 19 | 12 | 0 | -0.000719 | +0.016854 |
| SPY | 2019-2020 | 5 | neutral | 196 | 26 | +0.005612 | +0.007247 | -0.113958 | +0.069159 | 120 | 76 | 0 | +0.001765 | +0.000831 |
| SPY | 2019-2020 | 20 | all | 505 | 1 | +0.016576 | +0.025657 | -0.311755 | +0.234015 | 383 | 122 | 0 |  |  |
| SPY | 2019-2020 | 20 | bullish | 278 | 19 | +0.005930 | +0.020858 | -0.289394 | +0.113178 | 196 | 82 | 0 | -0.010646 | -0.004799 |
| SPY | 2019-2020 | 20 | bearish | 31 | 8 | +0.064975 | +0.070430 | -0.192898 | +0.234015 | 25 | 6 | 0 | +0.048399 | +0.044772 |
| SPY | 2019-2020 | 20 | neutral | 196 | 26 | +0.024021 | +0.034249 | -0.311755 | +0.182394 | 162 | 34 | 0 | +0.007445 | +0.008592 |
| SPY | 2021-2022 | 1 | all | 503 | 1 | +0.000132 | +0.000494 | -0.033573 | +0.047994 | 264 | 238 | 1 |  |  |
| SPY | 2021-2022 | 1 | bullish | 200 | 21 | -0.000057 | -0.000039 | -0.033573 | +0.030823 | 99 | 100 | 1 | -0.000189 | -0.000533 |
| SPY | 2021-2022 | 1 | bearish | 83 | 17 | +0.001565 | +0.002684 | -0.029630 | +0.047994 | 48 | 35 | 0 | +0.001432 | +0.002190 |
| SPY | 2021-2022 | 1 | neutral | 220 | 39 | -0.000236 | +0.000571 | -0.027361 | +0.024087 | 117 | 103 | 0 | -0.000368 | +0.000077 |
| SPY | 2021-2022 | 5 | all | 503 | 1 | +0.000567 | +0.003218 | -0.096780 | +0.067221 | 273 | 230 | 0 |  |  |
| SPY | 2021-2022 | 5 | bullish | 200 | 21 | -0.000450 | +0.001174 | -0.054770 | +0.040367 | 109 | 91 | 0 | -0.001017 | -0.002044 |
| SPY | 2021-2022 | 5 | bearish | 83 | 17 | +0.008241 | +0.010133 | -0.071490 | +0.067221 | 49 | 34 | 0 | +0.007674 | +0.006915 |
| SPY | 2021-2022 | 5 | neutral | 220 | 39 | -0.001403 | +0.001814 | -0.096780 | +0.055069 | 115 | 105 | 0 | -0.001970 | -0.001404 |
| SPY | 2021-2022 | 20 | all | 503 | 1 | +0.002871 | +0.010213 | -0.126366 | +0.124140 | 297 | 206 | 0 |  |  |
| SPY | 2021-2022 | 20 | bullish | 200 | 21 | -0.002824 | +0.005805 | -0.122654 | +0.058849 | 116 | 84 | 0 | -0.005696 | -0.004408 |
| SPY | 2021-2022 | 20 | bearish | 83 | 17 | +0.025376 | +0.037084 | -0.080338 | +0.124140 | 57 | 26 | 0 | +0.022505 | +0.026871 |
| SPY | 2021-2022 | 20 | neutral | 220 | 39 | -0.000441 | +0.015122 | -0.126366 | +0.110806 | 124 | 96 | 0 | -0.003313 | +0.004909 |
| SPY | 2023-2024 | 1 | all | 502 | 1 | +0.000391 | +0.000653 | -0.029306 | +0.024016 | 282 | 220 | 0 |  |  |
| SPY | 2023-2024 | 1 | bullish | 267 | 16 | +0.000470 | +0.000546 | -0.029306 | +0.015457 | 152 | 115 | 0 | +0.000079 | -0.000107 |
| SPY | 2023-2024 | 1 | bearish | 31 | 8 | +0.001324 | +0.001746 | -0.011245 | +0.024016 | 19 | 12 | 0 | +0.000933 | +0.001093 |
| SPY | 2023-2024 | 1 | neutral | 204 | 24 | +0.000145 | +0.000852 | -0.020733 | +0.016123 | 111 | 93 | 0 | -0.000245 | +0.000199 |
| SPY | 2023-2024 | 5 | all | 502 | 1 | +0.003949 | +0.005523 | -0.061368 | +0.051093 | 313 | 189 | 0 |  |  |
| SPY | 2023-2024 | 5 | bullish | 267 | 16 | +0.003106 | +0.004464 | -0.033476 | +0.031806 | 167 | 100 | 0 | -0.000843 | -0.001059 |
| SPY | 2023-2024 | 5 | bearish | 31 | 8 | +0.009843 | +0.012666 | -0.031527 | +0.051093 | 18 | 13 | 0 | +0.005894 | +0.007143 |
| SPY | 2023-2024 | 5 | neutral | 204 | 24 | +0.004157 | +0.006857 | -0.061368 | +0.049094 | 128 | 76 | 0 | +0.000208 | +0.001334 |
| SPY | 2023-2024 | 20 | all | 502 | 1 | +0.016526 | +0.021535 | -0.076197 | +0.101712 | 366 | 136 | 0 |  |  |
| SPY | 2023-2024 | 20 | bullish | 267 | 16 | +0.011162 | +0.019772 | -0.076197 | +0.066763 | 184 | 83 | 0 | -0.005365 | -0.001763 |
| SPY | 2023-2024 | 20 | bearish | 31 | 8 | +0.034859 | +0.043462 | -0.044293 | +0.099254 | 20 | 11 | 0 | +0.018333 | +0.021927 |
| SPY | 2023-2024 | 20 | neutral | 204 | 24 | +0.020762 | +0.022883 | -0.059790 | +0.101712 | 162 | 42 | 0 | +0.004235 | +0.001348 |
| QQQ | 2015-2016 | 1 | all | 504 | 1 | +0.000157 | +0.000554 | -0.038993 | +0.044890 | 263 | 238 | 3 |  |  |
| QQQ | 2015-2016 | 1 | bullish | 173 | 26 | -0.000586 | -0.000178 | -0.024422 | +0.017959 | 81 | 92 | 0 | -0.000742 | -0.000732 |
| QQQ | 2015-2016 | 1 | bearish | 68 | 14 | -0.000170 | +0.001974 | -0.038407 | +0.031845 | 39 | 29 | 0 | -0.000327 | +0.001420 |
| QQQ | 2015-2016 | 1 | neutral | 263 | 41 | +0.000730 | +0.001180 | -0.038993 | +0.044890 | 143 | 117 | 3 | +0.000573 | +0.000626 |
| QQQ | 2015-2016 | 5 | all | 504 | 1 | +0.001794 | +0.003123 | -0.115205 | +0.120874 | 294 | 210 | 0 |  |  |
| QQQ | 2015-2016 | 5 | bullish | 173 | 26 | -0.002416 | -0.000497 | -0.052014 | +0.028342 | 85 | 88 | 0 | -0.004211 | -0.003620 |
| QQQ | 2015-2016 | 5 | bearish | 68 | 14 | +0.007698 | +0.011858 | -0.063308 | +0.061492 | 43 | 25 | 0 | +0.005904 | +0.008735 |
| QQQ | 2015-2016 | 5 | neutral | 263 | 41 | +0.003038 | +0.005521 | -0.115205 | +0.120874 | 166 | 97 | 0 | +0.001243 | +0.002398 |
| QQQ | 2015-2016 | 20 | all | 504 | 1 | +0.008176 | +0.011022 | -0.119242 | +0.129365 | 317 | 186 | 1 |  |  |
| QQQ | 2015-2016 | 20 | bullish | 173 | 26 | -0.002848 | +0.001795 | -0.106830 | +0.049487 | 90 | 83 | 0 | -0.011024 | -0.009227 |
| QQQ | 2015-2016 | 20 | bearish | 68 | 14 | +0.023844 | +0.027937 | -0.087572 | +0.129365 | 48 | 19 | 1 | +0.015668 | +0.016916 |
| QQQ | 2015-2016 | 20 | neutral | 263 | 41 | +0.011376 | +0.015933 | -0.119242 | +0.121511 | 179 | 84 | 0 | +0.003200 | +0.004911 |
| QQQ | 2017-2018 | 1 | all | 502 | 1 | -0.000000 | +0.000634 | -0.044664 | +0.050869 | 274 | 225 | 3 |  |  |
| QQQ | 2017-2018 | 1 | bullish | 292 | 25 | -0.000087 | +0.000357 | -0.026158 | +0.016866 | 157 | 132 | 3 | -0.000086 | -0.000278 |
| QQQ | 2017-2018 | 1 | bearish | 43 | 8 | +0.000189 | -0.000567 | -0.044664 | +0.050869 | 21 | 22 | 0 | +0.000189 | -0.001201 |
| QQQ | 2017-2018 | 1 | neutral | 167 | 33 | +0.000102 | +0.001470 | -0.044640 | +0.041717 | 96 | 71 | 0 | +0.000102 | +0.000836 |
| QQQ | 2017-2018 | 5 | all | 502 | 1 | +0.002217 | +0.004826 | -0.095493 | +0.067549 | 306 | 194 | 2 |  |  |
| QQQ | 2017-2018 | 5 | bullish | 292 | 25 | +0.000888 | +0.003441 | -0.082785 | +0.033376 | 174 | 117 | 1 | -0.001329 | -0.001385 |
| QQQ | 2017-2018 | 5 | bearish | 43 | 8 | +0.000936 | +0.001005 | -0.095493 | +0.067549 | 22 | 20 | 1 | -0.001281 | -0.003821 |
| QQQ | 2017-2018 | 5 | neutral | 167 | 33 | +0.004870 | +0.010088 | -0.069971 | +0.064773 | 110 | 57 | 0 | +0.002653 | +0.005262 |
| QQQ | 2017-2018 | 20 | all | 502 | 1 | +0.010890 | +0.015325 | -0.126057 | +0.124897 | 347 | 155 | 0 |  |  |
| QQQ | 2017-2018 | 20 | bullish | 292 | 25 | +0.010045 | +0.014052 | -0.122467 | +0.088449 | 206 | 86 | 0 | -0.000845 | -0.001273 |
| QQQ | 2017-2018 | 20 | bearish | 43 | 8 | -0.002663 | -0.012607 | -0.111125 | +0.124897 | 18 | 25 | 0 | -0.013553 | -0.027932 |
| QQQ | 2017-2018 | 20 | neutral | 167 | 33 | +0.015856 | +0.023071 | -0.126057 | +0.112711 | 123 | 44 | 0 | +0.004967 | +0.007746 |
| QQQ | 2019-2020 | 1 | all | 505 | 1 | +0.000669 | +0.001106 | -0.060746 | +0.043672 | 278 | 225 | 2 |  |  |
| QQQ | 2019-2020 | 1 | bullish | 294 | 21 | +0.000506 | +0.001232 | -0.035860 | +0.027147 | 165 | 127 | 2 | -0.000163 | +0.000126 |
| QQQ | 2019-2020 | 1 | bearish | 24 | 6 | +0.003620 | +0.002611 | -0.060746 | +0.043672 | 13 | 11 | 0 | +0.002951 | +0.001505 |
| QQQ | 2019-2020 | 1 | neutral | 187 | 26 | +0.000547 | +0.000754 | -0.035297 | +0.036097 | 100 | 87 | 0 | -0.000122 | -0.000352 |
| QQQ | 2019-2020 | 5 | all | 505 | 1 | +0.006601 | +0.008288 | -0.158172 | +0.106654 | 322 | 183 | 0 |  |  |
| QQQ | 2019-2020 | 5 | bullish | 294 | 21 | +0.005595 | +0.008117 | -0.119729 | +0.063369 | 200 | 94 | 0 | -0.001006 | -0.000171 |
| QQQ | 2019-2020 | 5 | bearish | 24 | 6 | +0.025576 | +0.035326 | -0.086331 | +0.106654 | 16 | 8 | 0 | +0.018975 | +0.027038 |
| QQQ | 2019-2020 | 5 | neutral | 187 | 26 | +0.005746 | +0.007616 | -0.158172 | +0.083723 | 106 | 81 | 0 | -0.000854 | -0.000672 |
| QQQ | 2019-2020 | 20 | all | 505 | 1 | +0.028637 | +0.039792 | -0.274946 | +0.244676 | 397 | 108 | 0 |  |  |
| QQQ | 2019-2020 | 20 | bullish | 294 | 21 | +0.019433 | +0.037883 | -0.274946 | +0.132769 | 226 | 68 | 0 | -0.009204 | -0.001909 |
| QQQ | 2019-2020 | 20 | bearish | 24 | 6 | +0.121006 | +0.101727 | -0.014798 | +0.244676 | 23 | 1 | 0 | +0.092369 | +0.061935 |
| QQQ | 2019-2020 | 20 | neutral | 187 | 26 | +0.031253 | +0.036683 | -0.236461 | +0.185257 | 148 | 39 | 0 | +0.002616 | -0.003108 |
| QQQ | 2021-2022 | 1 | all | 503 | 1 | -0.000036 | +0.000660 | -0.040090 | +0.067902 | 263 | 240 | 0 |  |  |
| QQQ | 2021-2022 | 1 | bullish | 153 | 20 | -0.000136 | +0.000423 | -0.020934 | +0.021642 | 79 | 74 | 0 | -0.000100 | -0.000238 |
| QQQ | 2021-2022 | 1 | bearish | 111 | 18 | +0.001057 | +0.001005 | -0.038569 | +0.067902 | 59 | 52 | 0 | +0.001094 | +0.000345 |
| QQQ | 2021-2022 | 1 | neutral | 239 | 37 | -0.000480 | +0.001370 | -0.040090 | +0.044581 | 125 | 114 | 0 | -0.000444 | +0.000710 |
| QQQ | 2021-2022 | 5 | all | 503 | 1 | -0.000870 | +0.000545 | -0.107232 | +0.091000 | 257 | 246 | 0 |  |  |
| QQQ | 2021-2022 | 5 | bullish | 153 | 20 | -0.001756 | -0.000530 | -0.064260 | +0.044829 | 75 | 78 | 0 | -0.000886 | -0.001075 |
| QQQ | 2021-2022 | 5 | bearish | 111 | 18 | +0.004093 | +0.004474 | -0.075804 | +0.091000 | 61 | 50 | 0 | +0.004963 | +0.003928 |
| QQQ | 2021-2022 | 5 | neutral | 239 | 37 | -0.002607 | +0.000610 | -0.107232 | +0.080781 | 121 | 118 | 0 | -0.001737 | +0.000065 |
| QQQ | 2021-2022 | 20 | all | 503 | 1 | -0.002782 | +0.001216 | -0.159595 | +0.151737 | 254 | 249 | 0 |  |  |
| QQQ | 2021-2022 | 20 | bullish | 153 | 20 | -0.019434 | -0.019799 | -0.150076 | +0.071053 | 59 | 94 | 0 | -0.016653 | -0.021015 |
| QQQ | 2021-2022 | 20 | bearish | 111 | 18 | +0.013351 | +0.014665 | -0.106811 | +0.139639 | 64 | 47 | 0 | +0.016133 | +0.013448 |
| QQQ | 2021-2022 | 20 | neutral | 239 | 37 | +0.000386 | +0.011479 | -0.159595 | +0.151737 | 131 | 108 | 0 | +0.003168 | +0.010263 |
| QQQ | 2023-2024 | 1 | all | 502 | 1 | +0.000611 | +0.001308 | -0.034906 | +0.029564 | 280 | 222 | 0 |  |  |
| QQQ | 2023-2024 | 1 | bullish | 275 | 24 | +0.000279 | +0.000735 | -0.034906 | +0.022420 | 148 | 127 | 0 | -0.000332 | -0.000573 |
| QQQ | 2023-2024 | 1 | bearish | 42 | 8 | +0.001580 | +0.004084 | -0.026249 | +0.025446 | 24 | 18 | 0 | +0.000969 | +0.002777 |
| QQQ | 2023-2024 | 1 | neutral | 185 | 32 | +0.000885 | +0.001586 | -0.030646 | +0.029564 | 108 | 77 | 0 | +0.000274 | +0.000278 |
| QQQ | 2023-2024 | 5 | all | 502 | 1 | +0.006171 | +0.006639 | -0.078409 | +0.067534 | 314 | 188 | 0 |  |  |
| QQQ | 2023-2024 | 5 | bullish | 275 | 24 | +0.004114 | +0.003170 | -0.043032 | +0.052546 | 166 | 109 | 0 | -0.002057 | -0.003469 |
| QQQ | 2023-2024 | 5 | bearish | 42 | 8 | +0.023472 | +0.028237 | -0.043955 | +0.061960 | 31 | 11 | 0 | +0.017302 | +0.021598 |
| QQQ | 2023-2024 | 5 | neutral | 185 | 32 | +0.005300 | +0.010165 | -0.078409 | +0.067534 | 117 | 68 | 0 | -0.000870 | +0.003526 |
| QQQ | 2023-2024 | 20 | all | 502 | 1 | +0.025069 | +0.026373 | -0.135766 | +0.180579 | 377 | 124 | 1 |  |  |
| QQQ | 2023-2024 | 20 | bullish | 275 | 24 | +0.017688 | +0.022668 | -0.135766 | +0.116856 | 199 | 76 | 0 | -0.007381 | -0.003705 |
| QQQ | 2023-2024 | 20 | bearish | 42 | 8 | +0.051187 | +0.053375 | -0.049455 | +0.180579 | 33 | 9 | 0 | +0.026118 | +0.027001 |
| QQQ | 2023-2024 | 20 | neutral | 185 | 32 | +0.030110 | +0.031019 | -0.059266 | +0.149876 | 145 | 39 | 1 | +0.005042 | +0.004645 |
| IWM | 2015-2016 | 1 | all | 504 | 1 | +0.000370 | +0.000797 | -0.038229 | +0.037771 | 271 | 232 | 1 |  |  |
| IWM | 2015-2016 | 1 | bullish | 189 | 24 | +0.000208 | +0.000913 | -0.024377 | +0.015645 | 108 | 81 | 0 | -0.000162 | +0.000116 |
| IWM | 2015-2016 | 1 | bearish | 85 | 11 | -0.001045 | -0.001196 | -0.038229 | +0.029188 | 41 | 44 | 0 | -0.001416 | -0.001993 |
| IWM | 2015-2016 | 1 | neutral | 230 | 36 | +0.001026 | +0.000770 | -0.021428 | +0.037771 | 122 | 107 | 1 | +0.000656 | -0.000027 |
| IWM | 2015-2016 | 5 | all | 504 | 1 | +0.001830 | +0.003833 | -0.089906 | +0.097138 | 284 | 219 | 1 |  |  |
| IWM | 2015-2016 | 5 | bullish | 189 | 24 | -0.000511 | +0.000664 | -0.041992 | +0.054223 | 99 | 89 | 1 | -0.002341 | -0.003170 |
| IWM | 2015-2016 | 5 | bearish | 85 | 11 | -0.001455 | -0.000759 | -0.085154 | +0.079792 | 42 | 43 | 0 | -0.003285 | -0.004592 |
| IWM | 2015-2016 | 5 | neutral | 230 | 36 | +0.004968 | +0.005819 | -0.089906 | +0.097138 | 143 | 87 | 0 | +0.003138 | +0.001985 |
| IWM | 2015-2016 | 20 | all | 504 | 1 | +0.006931 | +0.010016 | -0.133869 | +0.150915 | 291 | 213 | 0 |  |  |
| IWM | 2015-2016 | 20 | bullish | 189 | 24 | +0.001021 | -0.000161 | -0.053388 | +0.075576 | 93 | 96 | 0 | -0.005911 | -0.010177 |
| IWM | 2015-2016 | 20 | bearish | 85 | 11 | +0.008178 | +0.006242 | -0.121538 | +0.135299 | 44 | 41 | 0 | +0.001247 | -0.003774 |
| IWM | 2015-2016 | 20 | neutral | 230 | 36 | +0.011327 | +0.019279 | -0.133869 | +0.150915 | 154 | 76 | 0 | +0.004396 | +0.009263 |
| IWM | 2017-2018 | 1 | all | 502 | 1 | -0.000398 | +0.000165 | -0.040520 | +0.044742 | 255 | 244 | 3 |  |  |
| IWM | 2017-2018 | 1 | bullish | 186 | 35 | -0.000614 | -0.000333 | -0.019229 | +0.015670 | 89 | 96 | 1 | -0.000216 | -0.000498 |
| IWM | 2017-2018 | 1 | bearish | 63 | 8 | -0.001276 | -0.000414 | -0.036188 | +0.044742 | 28 | 34 | 1 | -0.000878 | -0.000579 |
| IWM | 2017-2018 | 1 | neutral | 253 | 42 | -0.000021 | +0.001027 | -0.040520 | +0.028585 | 138 | 114 | 1 | +0.000377 | +0.000862 |
| IWM | 2017-2018 | 5 | all | 502 | 1 | -0.000111 | +0.000517 | -0.089541 | +0.072331 | 258 | 243 | 1 |  |  |
| IWM | 2017-2018 | 5 | bullish | 186 | 35 | -0.000171 | +0.000348 | -0.061779 | +0.039573 | 94 | 92 | 0 | -0.000061 | -0.000169 |
| IWM | 2017-2018 | 5 | bearish | 63 | 8 | -0.001612 | +0.003626 | -0.089541 | +0.072331 | 32 | 30 | 1 | -0.001501 | +0.003109 |
| IWM | 2017-2018 | 5 | neutral | 253 | 42 | +0.000308 | +0.001253 | -0.069888 | +0.046766 | 132 | 121 | 0 | +0.000418 | +0.000736 |
| IWM | 2017-2018 | 20 | all | 502 | 1 | +0.002655 | +0.006580 | -0.156978 | +0.151964 | 301 | 200 | 1 |  |  |
| IWM | 2017-2018 | 20 | bullish | 186 | 35 | -0.002367 | -0.000119 | -0.103955 | +0.056452 | 92 | 93 | 1 | -0.005022 | -0.006699 |
| IWM | 2017-2018 | 20 | bearish | 63 | 8 | +0.002483 | +0.004560 | -0.156978 | +0.151964 | 35 | 28 | 0 | -0.000173 | -0.002020 |
| IWM | 2017-2018 | 20 | neutral | 253 | 42 | +0.006391 | +0.018283 | -0.139837 | +0.083583 | 174 | 79 | 0 | +0.003735 | +0.011703 |
| IWM | 2019-2020 | 1 | all | 505 | 1 | -0.000196 | +0.000389 | -0.046032 | +0.057848 | 259 | 243 | 3 |  |  |
| IWM | 2019-2020 | 1 | bullish | 218 | 24 | -0.000780 | -0.000121 | -0.041820 | +0.019667 | 106 | 109 | 3 | -0.000584 | -0.000510 |
| IWM | 2019-2020 | 1 | bearish | 53 | 10 | -0.000699 | -0.001149 | -0.046032 | +0.047248 | 26 | 27 | 0 | -0.000503 | -0.001537 |
| IWM | 2019-2020 | 1 | neutral | 234 | 33 | +0.000463 | +0.001063 | -0.029702 | +0.057848 | 127 | 107 | 0 | +0.000658 | +0.000675 |
| IWM | 2019-2020 | 5 | all | 505 | 1 | +0.003653 | +0.005608 | -0.230792 | +0.160709 | 298 | 207 | 0 |  |  |
| IWM | 2019-2020 | 5 | bullish | 218 | 24 | +0.003457 | +0.004161 | -0.113530 | +0.094770 | 126 | 92 | 0 | -0.000196 | -0.001447 |
| IWM | 2019-2020 | 5 | bearish | 53 | 10 | -0.006727 | +0.016470 | -0.230792 | +0.160709 | 32 | 21 | 0 | -0.010379 | +0.010862 |
| IWM | 2019-2020 | 5 | neutral | 234 | 33 | +0.006186 | +0.006335 | -0.095947 | +0.127800 | 140 | 94 | 0 | +0.002533 | +0.000727 |
| IWM | 2019-2020 | 20 | all | 505 | 1 | +0.018300 | +0.024820 | -0.404586 | +0.246182 | 345 | 160 | 0 |  |  |
| IWM | 2019-2020 | 20 | bullish | 218 | 24 | +0.008940 | +0.014766 | -0.404586 | +0.173913 | 136 | 82 | 0 | -0.009360 | -0.010053 |
| IWM | 2019-2020 | 20 | bearish | 53 | 10 | +0.016567 | +0.061169 | -0.385306 | +0.246182 | 41 | 12 | 0 | -0.001732 | +0.036350 |
| IWM | 2019-2020 | 20 | neutral | 234 | 33 | +0.027412 | +0.029409 | -0.373533 | +0.201741 | 168 | 66 | 0 | +0.009112 | +0.004590 |
| IWM | 2021-2022 | 1 | all | 503 | 1 | -0.000521 | -0.000269 | -0.044406 | +0.051614 | 245 | 258 | 0 |  |  |
| IWM | 2021-2022 | 1 | bullish | 111 | 20 | -0.000928 | -0.000109 | -0.036069 | +0.025316 | 54 | 57 | 0 | -0.000407 | +0.000160 |
| IWM | 2021-2022 | 1 | bearish | 109 | 27 | +0.002038 | +0.003581 | -0.030916 | +0.051614 | 61 | 48 | 0 | +0.002559 | +0.003850 |
| IWM | 2021-2022 | 1 | neutral | 283 | 46 | -0.001347 | -0.000907 | -0.044406 | +0.034967 | 130 | 153 | 0 | -0.000826 | -0.000638 |
| IWM | 2021-2022 | 5 | all | 503 | 1 | -0.001259 | -0.001305 | -0.109278 | +0.084537 | 245 | 258 | 0 |  |  |
| IWM | 2021-2022 | 5 | bullish | 111 | 20 | -0.002837 | -0.007793 | -0.081283 | +0.074836 | 45 | 66 | 0 | -0.001578 | -0.006488 |
| IWM | 2021-2022 | 5 | bearish | 109 | 27 | +0.008255 | +0.011857 | -0.081669 | +0.084537 | 67 | 42 | 0 | +0.009515 | +0.013162 |
| IWM | 2021-2022 | 5 | neutral | 283 | 46 | -0.004305 | -0.002637 | -0.109278 | +0.070681 | 133 | 150 | 0 | -0.003046 | -0.001332 |
| IWM | 2021-2022 | 20 | all | 503 | 1 | -0.003887 | -0.002359 | -0.143493 | +0.159711 | 245 | 258 | 0 |  |  |
| IWM | 2021-2022 | 20 | bullish | 111 | 20 | -0.021467 | -0.031845 | -0.143493 | +0.108343 | 38 | 73 | 0 | -0.017579 | -0.029486 |
| IWM | 2021-2022 | 20 | bearish | 109 | 27 | +0.018804 | +0.014121 | -0.093150 | +0.159711 | 68 | 41 | 0 | +0.022691 | +0.016480 |
| IWM | 2021-2022 | 20 | neutral | 283 | 46 | -0.005732 | -0.001032 | -0.141763 | +0.150615 | 139 | 144 | 0 | -0.001845 | +0.001327 |
| IWM | 2023-2024 | 1 | all | 502 | 1 | -0.000154 | +0.000083 | -0.049087 | +0.033298 | 252 | 250 | 0 |  |  |
| IWM | 2023-2024 | 1 | bullish | 170 | 28 | -0.001199 | -0.001689 | -0.032131 | +0.033298 | 76 | 94 | 0 | -0.001045 | -0.001772 |
| IWM | 2023-2024 | 1 | bearish | 72 | 17 | +0.000579 | +0.000700 | -0.027646 | +0.026302 | 40 | 32 | 0 | +0.000733 | +0.000617 |
| IWM | 2023-2024 | 1 | neutral | 260 | 44 | +0.000326 | +0.000681 | -0.049087 | +0.024916 | 136 | 124 | 0 | +0.000480 | +0.000598 |
| IWM | 2023-2024 | 5 | all | 502 | 1 | +0.002091 | +0.000601 | -0.097377 | +0.110287 | 258 | 244 | 0 |  |  |
| IWM | 2023-2024 | 5 | bullish | 170 | 28 | -0.004938 | -0.006441 | -0.097377 | +0.073918 | 68 | 102 | 0 | -0.007029 | -0.007042 |
| IWM | 2023-2024 | 5 | bearish | 72 | 17 | +0.001695 | -0.000606 | -0.044079 | +0.065328 | 36 | 36 | 0 | -0.000396 | -0.001207 |
| IWM | 2023-2024 | 5 | neutral | 260 | 44 | +0.006797 | +0.004467 | -0.081315 | +0.110287 | 154 | 106 | 0 | +0.004706 | +0.003866 |
| IWM | 2023-2024 | 20 | all | 502 | 1 | +0.008755 | +0.007829 | -0.107619 | +0.143097 | 280 | 222 | 0 |  |  |
| IWM | 2023-2024 | 20 | bullish | 170 | 28 | -0.007218 | -0.005105 | -0.107619 | +0.143097 | 75 | 95 | 0 | -0.015973 | -0.012934 |
| IWM | 2023-2024 | 20 | bearish | 72 | 17 | +0.007289 | +0.008150 | -0.082863 | +0.123731 | 38 | 34 | 0 | -0.001466 | +0.000321 |
| IWM | 2023-2024 | 20 | neutral | 260 | 44 | +0.019605 | +0.021863 | -0.093531 | +0.135919 | 167 | 93 | 0 | +0.010850 | +0.014034 |
| TLT | 2015-2016 | 1 | all | 504 | 1 | -0.000099 | +0.000115 | -0.020830 | +0.015824 | 254 | 248 | 2 |  |  |
| TLT | 2015-2016 | 1 | bullish | 124 | 18 | +0.000446 | +0.000148 | -0.018269 | +0.015506 | 63 | 61 | 0 | +0.000545 | +0.000033 |
| TLT | 2015-2016 | 1 | bearish | 122 | 11 | -0.000179 | +0.000383 | -0.020830 | +0.013406 | 63 | 59 | 0 | -0.000080 | +0.000268 |
| TLT | 2015-2016 | 1 | neutral | 258 | 29 | -0.000323 | +0.000000 | -0.016512 | +0.015824 | 128 | 128 | 2 | -0.000224 | -0.000115 |
| TLT | 2015-2016 | 5 | all | 504 | 1 | -0.000546 | +0.000506 | -0.074111 | +0.045586 | 261 | 242 | 1 |  |  |
| TLT | 2015-2016 | 5 | bullish | 124 | 18 | +0.001131 | +0.002292 | -0.046372 | +0.045586 | 70 | 54 | 0 | +0.001677 | +0.001786 |
| TLT | 2015-2016 | 5 | bearish | 122 | 11 | -0.001508 | +0.000467 | -0.074111 | +0.035427 | 62 | 59 | 1 | -0.000962 | -0.000040 |
| TLT | 2015-2016 | 5 | neutral | 258 | 29 | -0.000897 | +0.000074 | -0.045024 | +0.044644 | 129 | 129 | 0 | -0.000351 | -0.000432 |
| TLT | 2015-2016 | 20 | all | 504 | 1 | -0.003200 | +0.001017 | -0.094146 | +0.078670 | 256 | 248 | 0 |  |  |
| TLT | 2015-2016 | 20 | bullish | 124 | 18 | -0.002063 | -0.005912 | -0.071909 | +0.077434 | 55 | 69 | 0 | +0.001137 | -0.006929 |
| TLT | 2015-2016 | 20 | bearish | 122 | 11 | -0.011419 | -0.012970 | -0.094146 | +0.077563 | 50 | 72 | 0 | -0.008219 | -0.013987 |
| TLT | 2015-2016 | 20 | neutral | 258 | 29 | +0.000140 | +0.004981 | -0.091340 | +0.078670 | 151 | 107 | 0 | +0.003340 | +0.003964 |
| TLT | 2017-2018 | 1 | all | 502 | 1 | +0.000228 | +0.000161 | -0.014533 | +0.012923 | 258 | 238 | 6 |  |  |
| TLT | 2017-2018 | 1 | bullish | 112 | 18 | -0.000198 | +0.000000 | -0.010409 | +0.008908 | 55 | 54 | 3 | -0.000427 | -0.000161 |
| TLT | 2017-2018 | 1 | bearish | 105 | 18 | -0.000311 | -0.000356 | -0.014533 | +0.012923 | 52 | 53 | 0 | -0.000539 | -0.000517 |
| TLT | 2017-2018 | 1 | neutral | 285 | 36 | +0.000595 | +0.000244 | -0.009607 | +0.012702 | 151 | 131 | 3 | +0.000366 | +0.000083 |
| TLT | 2017-2018 | 5 | all | 502 | 1 | +0.000360 | +0.000418 | -0.034370 | +0.042203 | 255 | 246 | 1 |  |  |
| TLT | 2017-2018 | 5 | bullish | 112 | 18 | -0.000948 | -0.000523 | -0.027537 | +0.023809 | 55 | 57 | 0 | -0.001308 | -0.000941 |
| TLT | 2017-2018 | 5 | bearish | 105 | 18 | +0.001528 | +0.001265 | -0.034370 | +0.042203 | 54 | 50 | 1 | +0.001167 | +0.000847 |
| TLT | 2017-2018 | 5 | neutral | 285 | 36 | +0.000444 | +0.000421 | -0.026064 | +0.036798 | 146 | 139 | 0 | +0.000084 | +0.000003 |
| TLT | 2017-2018 | 20 | all | 502 | 1 | +0.000533 | +0.000976 | -0.053913 | +0.065138 | 260 | 242 | 0 |  |  |
| TLT | 2017-2018 | 20 | bullish | 112 | 18 | -0.007778 | -0.011445 | -0.040043 | +0.039181 | 34 | 78 | 0 | -0.008311 | -0.012421 |
| TLT | 2017-2018 | 20 | bearish | 105 | 18 | +0.004100 | +0.007716 | -0.053607 | +0.054545 | 66 | 39 | 0 | +0.003568 | +0.006740 |
| TLT | 2017-2018 | 20 | neutral | 285 | 36 | +0.002485 | +0.003867 | -0.053913 | +0.065138 | 160 | 125 | 0 | +0.001952 | +0.002891 |
| TLT | 2019-2020 | 1 | all | 505 | 1 | -0.000097 | +0.000082 | -0.064343 | +0.053968 | 257 | 245 | 3 |  |  |
| TLT | 2019-2020 | 1 | bullish | 180 | 19 | -0.000699 | -0.000136 | -0.064343 | +0.053968 | 85 | 94 | 1 | -0.000601 | -0.000218 |
| TLT | 2019-2020 | 1 | bearish | 67 | 18 | +0.000451 | -0.000287 | -0.010634 | +0.012982 | 32 | 35 | 0 | +0.000548 | -0.000369 |
| TLT | 2019-2020 | 1 | neutral | 258 | 37 | +0.000180 | +0.000414 | -0.055548 | +0.039987 | 140 | 116 | 2 | +0.000277 | +0.000332 |
| TLT | 2019-2020 | 5 | all | 505 | 1 | +0.001886 | +0.001520 | -0.140480 | +0.113647 | 283 | 221 | 1 |  |  |
| TLT | 2019-2020 | 5 | bullish | 180 | 19 | +0.001769 | +0.002041 | -0.140480 | +0.113647 | 104 | 75 | 1 | -0.000118 | +0.000521 |
| TLT | 2019-2020 | 5 | bearish | 67 | 18 | +0.003277 | +0.004145 | -0.040089 | +0.059957 | 40 | 27 | 0 | +0.001390 | +0.002624 |
| TLT | 2019-2020 | 5 | neutral | 258 | 37 | +0.001607 | +0.001118 | -0.037305 | +0.106090 | 139 | 119 | 0 | -0.000279 | -0.000402 |
| TLT | 2019-2020 | 20 | all | 505 | 1 | +0.009335 | +0.002346 | -0.065179 | +0.180496 | 267 | 238 | 0 |  |  |
| TLT | 2019-2020 | 20 | bullish | 180 | 19 | +0.010996 | +0.000972 | -0.065179 | +0.180496 | 91 | 89 | 0 | +0.001662 | -0.001374 |
| TLT | 2019-2020 | 20 | bearish | 67 | 18 | +0.004815 | +0.006191 | -0.046438 | +0.061302 | 41 | 26 | 0 | -0.004520 | +0.003845 |
| TLT | 2019-2020 | 20 | neutral | 258 | 37 | +0.009349 | +0.002285 | -0.051522 | +0.157469 | 135 | 123 | 0 | +0.000014 | -0.000061 |
| TLT | 2021-2022 | 1 | all | 503 | 1 | +0.000088 | +0.000359 | -0.024099 | +0.030152 | 263 | 238 | 2 |  |  |
| TLT | 2021-2022 | 1 | bullish | 80 | 15 | -0.000518 | +0.000413 | -0.022056 | +0.017603 | 41 | 37 | 2 | -0.000606 | +0.000054 |
| TLT | 2021-2022 | 1 | bearish | 227 | 19 | +0.000113 | +0.000804 | -0.017455 | +0.030152 | 121 | 106 | 0 | +0.000025 | +0.000445 |
| TLT | 2021-2022 | 1 | neutral | 196 | 35 | +0.000306 | +0.000080 | -0.024099 | +0.025303 | 101 | 95 | 0 | +0.000218 | -0.000280 |
| TLT | 2021-2022 | 5 | all | 503 | 1 | -0.002776 | -0.002440 | -0.061638 | +0.061270 | 236 | 267 | 0 |  |  |
| TLT | 2021-2022 | 5 | bullish | 80 | 15 | -0.003561 | -0.000758 | -0.044433 | +0.040726 | 40 | 40 | 0 | -0.000785 | +0.001683 |
| TLT | 2021-2022 | 5 | bearish | 227 | 19 | -0.005043 | -0.006001 | -0.061638 | +0.057664 | 90 | 137 | 0 | -0.002267 | -0.003560 |
| TLT | 2021-2022 | 5 | neutral | 196 | 35 | +0.000170 | +0.003071 | -0.051618 | +0.061270 | 106 | 90 | 0 | +0.002946 | +0.005511 |
| TLT | 2021-2022 | 20 | all | 503 | 1 | -0.012513 | -0.014320 | -0.115699 | +0.166809 | 201 | 302 | 0 |  |  |
| TLT | 2021-2022 | 20 | bullish | 80 | 15 | -0.005513 | -0.003677 | -0.063808 | +0.055075 | 38 | 42 | 0 | +0.006999 | +0.010643 |
| TLT | 2021-2022 | 20 | bearish | 227 | 19 | -0.020399 | -0.028437 | -0.115699 | +0.166809 | 69 | 158 | 0 | -0.007886 | -0.014117 |
| TLT | 2021-2022 | 20 | neutral | 196 | 35 | -0.006236 | -0.003697 | -0.111802 | +0.096183 | 94 | 102 | 0 | +0.006276 | +0.010623 |
| TLT | 2023-2024 | 1 | all | 502 | 1 | +0.000303 | +0.000115 | -0.022487 | +0.024148 | 255 | 244 | 3 |  |  |
| TLT | 2023-2024 | 1 | bullish | 103 | 16 | +0.002008 | +0.002037 | -0.015894 | +0.018399 | 66 | 36 | 1 | +0.001705 | +0.001922 |
| TLT | 2023-2024 | 1 | bearish | 175 | 19 | +0.000313 | -0.000106 | -0.022487 | +0.017268 | 87 | 88 | 0 | +0.000011 | -0.000221 |
| TLT | 2023-2024 | 1 | neutral | 224 | 35 | -0.000489 | -0.000746 | -0.021904 | +0.024148 | 102 | 120 | 2 | -0.000792 | -0.000861 |
| TLT | 2023-2024 | 5 | all | 502 | 1 | -0.001006 | -0.001293 | -0.055137 | +0.054675 | 239 | 263 | 0 |  |  |
| TLT | 2023-2024 | 5 | bullish | 103 | 16 | +0.000626 | -0.000860 | -0.044222 | +0.054675 | 49 | 54 | 0 | +0.001632 | +0.000433 |
| TLT | 2023-2024 | 5 | bearish | 175 | 19 | -0.001798 | -0.001300 | -0.055137 | +0.047834 | 84 | 91 | 0 | -0.000792 | -0.000007 |
| TLT | 2023-2024 | 5 | neutral | 224 | 35 | -0.001137 | -0.002210 | -0.040855 | +0.053867 | 106 | 118 | 0 | -0.000132 | -0.000917 |
| TLT | 2023-2024 | 20 | all | 502 | 1 | -0.006346 | -0.007974 | -0.095972 | +0.109071 | 215 | 287 | 0 |  |  |
| TLT | 2023-2024 | 20 | bullish | 103 | 16 | -0.007968 | -0.011907 | -0.086669 | +0.091195 | 44 | 59 | 0 | -0.001622 | -0.003933 |
| TLT | 2023-2024 | 20 | bearish | 175 | 19 | -0.005250 | -0.001142 | -0.095972 | +0.102213 | 83 | 92 | 0 | +0.001096 | +0.006833 |
| TLT | 2023-2024 | 20 | neutral | 224 | 35 | -0.006456 | -0.012461 | -0.085860 | +0.109071 | 88 | 136 | 0 | -0.000110 | -0.004486 |
| GLD | 2015-2016 | 1 | all | 504 | 1 | -0.000231 | -0.000337 | -0.022290 | +0.026997 | 232 | 270 | 2 |  |  |
| GLD | 2015-2016 | 1 | bullish | 117 | 20 | -0.000044 | -0.000094 | -0.019955 | +0.025932 | 58 | 59 | 0 | +0.000187 | +0.000243 |
| GLD | 2015-2016 | 1 | bearish | 133 | 15 | -0.000586 | -0.000197 | -0.021312 | +0.018490 | 58 | 74 | 1 | -0.000355 | +0.000140 |
| GLD | 2015-2016 | 1 | neutral | 254 | 35 | -0.000132 | -0.000471 | -0.022290 | +0.026997 | 116 | 137 | 1 | +0.000100 | -0.000134 |
| GLD | 2015-2016 | 5 | all | 504 | 1 | -0.000351 | -0.002281 | -0.057763 | +0.084434 | 231 | 272 | 1 |  |  |
| GLD | 2015-2016 | 5 | bullish | 117 | 20 | +0.001693 | -0.003908 | -0.050586 | +0.084434 | 56 | 61 | 0 | +0.002043 | -0.001627 |
| GLD | 2015-2016 | 5 | bearish | 133 | 15 | -0.001905 | -0.002001 | -0.047748 | +0.046019 | 59 | 73 | 1 | -0.001555 | +0.000280 |
| GLD | 2015-2016 | 5 | neutral | 254 | 35 | -0.000478 | -0.001855 | -0.057763 | +0.046640 | 116 | 138 | 0 | -0.000127 | +0.000426 |
| GLD | 2015-2016 | 20 | all | 504 | 1 | -0.001428 | -0.002064 | -0.100322 | +0.147566 | 240 | 264 | 0 |  |  |
| GLD | 2015-2016 | 20 | bullish | 117 | 20 | -0.006645 | -0.010264 | -0.089259 | +0.126679 | 46 | 71 | 0 | -0.005217 | -0.008200 |
| GLD | 2015-2016 | 20 | bearish | 133 | 15 | -0.002822 | +0.001473 | -0.081858 | +0.075316 | 70 | 63 | 0 | -0.001394 | +0.003537 |
| GLD | 2015-2016 | 20 | neutral | 254 | 35 | +0.001705 | -0.001508 | -0.100322 | +0.147566 | 124 | 130 | 0 | +0.003133 | +0.000556 |
| GLD | 2017-2018 | 1 | all | 502 | 1 | +0.000053 | -0.000085 | -0.013908 | +0.017149 | 244 | 255 | 3 |  |  |
| GLD | 2017-2018 | 1 | bullish | 140 | 14 | +0.000178 | +0.000209 | -0.011048 | +0.011027 | 73 | 66 | 1 | +0.000126 | +0.000294 |
| GLD | 2017-2018 | 1 | bearish | 111 | 18 | +0.000178 | -0.000353 | -0.008737 | +0.009282 | 50 | 61 | 0 | +0.000125 | -0.000268 |
| GLD | 2017-2018 | 1 | neutral | 251 | 32 | -0.000073 | -0.000171 | -0.013908 | +0.017149 | 121 | 128 | 2 | -0.000126 | -0.000086 |
| GLD | 2017-2018 | 5 | all | 502 | 1 | +0.000801 | +0.000166 | -0.033299 | +0.037186 | 254 | 245 | 3 |  |  |
| GLD | 2017-2018 | 5 | bullish | 140 | 14 | +0.001442 | +0.001666 | -0.026272 | +0.028496 | 77 | 62 | 1 | +0.000641 | +0.001500 |
| GLD | 2017-2018 | 5 | bearish | 111 | 18 | +0.000192 | +0.000245 | -0.033299 | +0.032304 | 57 | 53 | 1 | -0.000609 | +0.000079 |
| GLD | 2017-2018 | 5 | neutral | 251 | 32 | +0.000712 | -0.000518 | -0.029500 | +0.037186 | 120 | 130 | 1 | -0.000088 | -0.000684 |
| GLD | 2017-2018 | 20 | all | 502 | 1 | +0.003046 | -0.000040 | -0.059980 | +0.065995 | 250 | 251 | 1 |  |  |
| GLD | 2017-2018 | 20 | bullish | 140 | 14 | -0.002189 | -0.005311 | -0.059980 | +0.050336 | 62 | 78 | 0 | -0.005236 | -0.005272 |
| GLD | 2017-2018 | 20 | bearish | 111 | 18 | -0.002065 | -0.007621 | -0.045533 | +0.065995 | 47 | 63 | 1 | -0.005111 | -0.007582 |
| GLD | 2017-2018 | 20 | neutral | 251 | 32 | +0.008227 | +0.004003 | -0.056869 | +0.061990 | 141 | 110 | 0 | +0.005181 | +0.004042 |
| GLD | 2019-2020 | 1 | all | 505 | 1 | +0.000004 | +0.000323 | -0.041092 | +0.030131 | 264 | 240 | 1 |  |  |
| GLD | 2019-2020 | 1 | bullish | 218 | 24 | -0.000309 | +0.000110 | -0.028354 | +0.021443 | 110 | 108 | 0 | -0.000313 | -0.000213 |
| GLD | 2019-2020 | 1 | bearish | 72 | 18 | +0.000520 | +0.001079 | -0.016391 | +0.008340 | 46 | 26 | 0 | +0.000516 | +0.000757 |
| GLD | 2019-2020 | 1 | neutral | 215 | 42 | +0.000149 | +0.000062 | -0.041092 | +0.030131 | 108 | 106 | 1 | +0.000145 | -0.000260 |
| GLD | 2019-2020 | 5 | all | 505 | 1 | +0.003285 | +0.003539 | -0.096595 | +0.089048 | 305 | 198 | 2 |  |  |
| GLD | 2019-2020 | 5 | bullish | 218 | 24 | +0.002229 | +0.003228 | -0.096595 | +0.058610 | 130 | 87 | 1 | -0.001056 | -0.000311 |
| GLD | 2019-2020 | 5 | bearish | 72 | 18 | +0.003739 | +0.003980 | -0.048144 | +0.035410 | 48 | 24 | 0 | +0.000454 | +0.000441 |
| GLD | 2019-2020 | 5 | neutral | 215 | 42 | +0.004203 | +0.002299 | -0.076161 | +0.089048 | 127 | 87 | 1 | +0.000919 | -0.001240 |
| GLD | 2019-2020 | 20 | all | 505 | 1 | +0.014268 | +0.006860 | -0.116025 | +0.173379 | 286 | 217 | 2 |  |  |
| GLD | 2019-2020 | 20 | bullish | 218 | 24 | +0.017594 | +0.012787 | -0.116025 | +0.140865 | 132 | 84 | 2 | +0.003326 | +0.005927 |
| GLD | 2019-2020 | 20 | bearish | 72 | 18 | +0.010810 | +0.007116 | -0.060750 | +0.085168 | 46 | 26 | 0 | -0.003459 | +0.000256 |
| GLD | 2019-2020 | 20 | neutral | 215 | 42 | +0.012054 | +0.000845 | -0.060414 | +0.173379 | 108 | 107 | 0 | -0.002214 | -0.006015 |
| GLD | 2021-2022 | 1 | all | 503 | 1 | -0.000009 | -0.000115 | -0.029848 | +0.022181 | 247 | 253 | 3 |  |  |
| GLD | 2021-2022 | 1 | bullish | 110 | 13 | +0.000037 | -0.000000 | -0.029848 | +0.016777 | 55 | 55 | 0 | +0.000046 | +0.000115 |
| GLD | 2021-2022 | 1 | bearish | 130 | 24 | -0.000250 | -0.000093 | -0.019333 | +0.019236 | 63 | 66 | 1 | -0.000241 | +0.000022 |
| GLD | 2021-2022 | 1 | neutral | 263 | 37 | +0.000091 | -0.000121 | -0.016100 | +0.022181 | 129 | 132 | 2 | +0.000100 | -0.000006 |
| GLD | 2021-2022 | 5 | all | 503 | 1 | -0.000123 | +0.001745 | -0.059434 | +0.063177 | 267 | 236 | 0 |  |  |
| GLD | 2021-2022 | 5 | bullish | 110 | 13 | +0.000728 | +0.002947 | -0.059434 | +0.063177 | 62 | 48 | 0 | +0.000851 | +0.001202 |
| GLD | 2021-2022 | 5 | bearish | 130 | 24 | +0.000646 | +0.003267 | -0.049478 | +0.055050 | 72 | 58 | 0 | +0.000768 | +0.001522 |
| GLD | 2021-2022 | 5 | neutral | 263 | 37 | -0.000859 | +0.000420 | -0.055523 | +0.057247 | 133 | 130 | 0 | -0.000736 | -0.001325 |
| GLD | 2021-2022 | 20 | all | 503 | 1 | +0.001321 | +0.002315 | -0.092283 | +0.125867 | 262 | 240 | 1 |  |  |
| GLD | 2021-2022 | 20 | bullish | 110 | 13 | +0.003289 | +0.013696 | -0.092283 | +0.093127 | 62 | 48 | 0 | +0.001967 | +0.011381 |
| GLD | 2021-2022 | 20 | bearish | 130 | 24 | +0.005877 | +0.005336 | -0.084254 | +0.113736 | 73 | 56 | 1 | +0.004556 | +0.003020 |
| GLD | 2021-2022 | 20 | neutral | 263 | 37 | -0.001753 | -0.001708 | -0.079075 | +0.125867 | 127 | 136 | 0 | -0.003075 | -0.004023 |
| GLD | 2023-2024 | 1 | all | 502 | 1 | +0.000057 | -0.000054 | -0.022446 | +0.020727 | 243 | 255 | 4 |  |  |
| GLD | 2023-2024 | 1 | bullish | 202 | 22 | +0.000168 | -0.000286 | -0.022446 | +0.017648 | 95 | 106 | 1 | +0.000111 | -0.000232 |
| GLD | 2023-2024 | 1 | bearish | 50 | 15 | +0.000189 | +0.000428 | -0.014202 | +0.009581 | 28 | 22 | 0 | +0.000132 | +0.000483 |
| GLD | 2023-2024 | 1 | neutral | 250 | 37 | -0.000059 | -0.000054 | -0.017695 | +0.020727 | 120 | 127 | 3 | -0.000116 | +0.000000 |
| GLD | 2023-2024 | 5 | all | 502 | 1 | +0.002960 | +0.001381 | -0.048420 | +0.051503 | 264 | 238 | 0 |  |  |
| GLD | 2023-2024 | 5 | bullish | 202 | 22 | +0.002155 | +0.002292 | -0.045866 | +0.051503 | 107 | 95 | 0 | -0.000806 | +0.000911 |
| GLD | 2023-2024 | 5 | bearish | 50 | 15 | +0.006979 | +0.008061 | -0.034861 | +0.049838 | 32 | 18 | 0 | +0.004018 | +0.006679 |
| GLD | 2023-2024 | 5 | neutral | 250 | 37 | +0.002808 | -0.000030 | -0.048420 | +0.050823 | 125 | 125 | 0 | -0.000153 | -0.001411 |
| GLD | 2023-2024 | 20 | all | 502 | 1 | +0.013891 | +0.010051 | -0.063900 | +0.114880 | 312 | 189 | 1 |  |  |
| GLD | 2023-2024 | 20 | bullish | 202 | 22 | +0.009245 | +0.010166 | -0.063900 | +0.108206 | 119 | 83 | 0 | -0.004646 | +0.000115 |
| GLD | 2023-2024 | 20 | bearish | 50 | 15 | +0.038565 | +0.025668 | -0.031289 | +0.114880 | 44 | 6 | 0 | +0.024674 | +0.015617 |
| GLD | 2023-2024 | 20 | neutral | 250 | 37 | +0.012711 | +0.005928 | -0.053979 | +0.102838 | 149 | 100 | 1 | -0.001181 | -0.004123 |

### trend_crossover

| symbol | segment | h | state | n | episodes | mean | median | min | max | pos | neg | zero | mean delta | median delta |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SPY | 2015-2016 | 1 | all | 504 | 1 | +0.000303 | +0.000444 | -0.041754 | +0.027560 | 265 | 235 | 4 |  |  |
| SPY | 2015-2016 | 1 | bullish | 8 | 8 | -0.000376 | +0.001103 | -0.009225 | +0.004015 | 5 | 3 | 0 | -0.000679 | +0.000658 |
| SPY | 2015-2016 | 1 | bearish | 8 | 8 | -0.000598 | -0.002080 | -0.010417 | +0.011978 | 3 | 5 | 0 | -0.000901 | -0.002524 |
| SPY | 2015-2016 | 1 | neutral | 488 | 17 | +0.000329 | +0.000444 | -0.041754 | +0.027560 | 257 | 227 | 4 | +0.000026 | +0.000000 |
| SPY | 2015-2016 | 5 | all | 504 | 1 | +0.001341 | +0.002023 | -0.104357 | +0.062883 | 285 | 218 | 1 |  |  |
| SPY | 2015-2016 | 5 | bullish | 8 | 8 | +0.004055 | +0.004672 | -0.006988 | +0.016903 | 6 | 2 | 0 | +0.002714 | +0.002649 |
| SPY | 2015-2016 | 5 | bearish | 8 | 8 | -0.015536 | -0.001468 | -0.104357 | +0.022739 | 3 | 5 | 0 | -0.016877 | -0.003491 |
| SPY | 2015-2016 | 5 | neutral | 488 | 17 | +0.001573 | +0.002023 | -0.098735 | +0.062883 | 276 | 211 | 1 | +0.000232 | +0.000000 |
| SPY | 2015-2016 | 20 | all | 504 | 1 | +0.005167 | +0.006208 | -0.106024 | +0.100437 | 303 | 201 | 0 |  |  |
| SPY | 2015-2016 | 20 | bullish | 8 | 8 | -0.008609 | +0.002348 | -0.070759 | +0.026321 | 4 | 4 | 0 | -0.013776 | -0.003861 |
| SPY | 2015-2016 | 20 | bearish | 8 | 8 | -0.012191 | -0.004238 | -0.069227 | +0.026051 | 2 | 6 | 0 | -0.017358 | -0.010447 |
| SPY | 2015-2016 | 20 | neutral | 488 | 17 | +0.005677 | +0.006582 | -0.106024 | +0.100437 | 297 | 191 | 0 | +0.000510 | +0.000373 |
| SPY | 2017-2018 | 1 | all | 502 | 1 | -0.000196 | +0.000143 | -0.038730 | +0.043268 | 261 | 235 | 6 |  |  |
| SPY | 2017-2018 | 1 | bullish | 3 | 3 | +0.001091 | -0.000375 | -0.001068 | +0.004717 | 1 | 2 | 0 | +0.001287 | -0.000518 |
| SPY | 2017-2018 | 1 | bearish | 4 | 4 | +0.003400 | +0.003213 | +0.000036 | +0.007139 | 4 | 0 | 0 | +0.003596 | +0.003070 |
| SPY | 2017-2018 | 1 | neutral | 495 | 7 | -0.000233 | +0.000132 | -0.038730 | +0.043268 | 256 | 233 | 6 | -0.000037 | -0.000011 |
| SPY | 2017-2018 | 5 | all | 502 | 1 | +0.000777 | +0.002563 | -0.088880 | +0.060219 | 305 | 195 | 2 |  |  |
| SPY | 2017-2018 | 5 | bullish | 3 | 3 | +0.001923 | +0.004344 | -0.003212 | +0.004636 | 2 | 1 | 0 | +0.001146 | +0.001781 |
| SPY | 2017-2018 | 5 | bearish | 4 | 4 | -0.007108 | -0.009003 | -0.024825 | +0.014399 | 2 | 2 | 0 | -0.007885 | -0.011566 |
| SPY | 2017-2018 | 5 | neutral | 495 | 7 | +0.000834 | +0.002548 | -0.088880 | +0.060219 | 301 | 192 | 2 | +0.000057 | -0.000016 |
| SPY | 2017-2018 | 20 | all | 502 | 1 | +0.005422 | +0.013065 | -0.122714 | +0.116879 | 340 | 162 | 0 |  |  |
| SPY | 2017-2018 | 20 | bullish | 3 | 3 | +0.021164 | +0.020286 | +0.017685 | +0.025520 | 3 | 0 | 0 | +0.015742 | +0.007221 |
| SPY | 2017-2018 | 20 | bearish | 4 | 4 | -0.009141 | -0.002350 | -0.064799 | +0.032936 | 2 | 2 | 0 | -0.014563 | -0.015415 |
| SPY | 2017-2018 | 20 | neutral | 495 | 7 | +0.005444 | +0.013003 | -0.122714 | +0.116879 | 335 | 160 | 0 | +0.000022 | -0.000062 |
| SPY | 2019-2020 | 1 | all | 505 | 1 | +0.000304 | +0.000804 | -0.056612 | +0.046810 | 284 | 218 | 3 |  |  |
| SPY | 2019-2020 | 1 | bullish | 5 | 5 | +0.000554 | +0.001436 | -0.008832 | +0.006849 | 3 | 2 | 0 | +0.000250 | +0.000631 |
| SPY | 2019-2020 | 1 | bearish | 4 | 4 | +0.007020 | +0.003993 | -0.001925 | +0.022017 | 2 | 2 | 0 | +0.006715 | +0.003189 |
| SPY | 2019-2020 | 1 | neutral | 496 | 10 | +0.000248 | +0.000804 | -0.056612 | +0.046810 | 279 | 214 | 3 | -0.000057 | -0.000000 |
| SPY | 2019-2020 | 5 | all | 505 | 1 | +0.003847 | +0.006416 | -0.157357 | +0.117623 | 331 | 174 | 0 |  |  |
| SPY | 2019-2020 | 5 | bullish | 5 | 5 | -0.006152 | +0.001333 | -0.047527 | +0.020097 | 3 | 2 | 0 | -0.009998 | -0.005083 |
| SPY | 2019-2020 | 5 | bearish | 4 | 4 | -0.003603 | +0.011443 | -0.057820 | +0.020525 | 3 | 1 | 0 | -0.007449 | +0.005026 |
| SPY | 2019-2020 | 5 | neutral | 496 | 10 | +0.004008 | +0.006414 | -0.157357 | +0.117623 | 325 | 171 | 0 | +0.000161 | -0.000002 |
| SPY | 2019-2020 | 20 | all | 505 | 1 | +0.016576 | +0.025657 | -0.311755 | +0.234015 | 383 | 122 | 0 |  |  |
| SPY | 2019-2020 | 20 | bullish | 5 | 5 | +0.032342 | +0.034393 | -0.010380 | +0.066629 | 4 | 1 | 0 | +0.015766 | +0.008736 |
| SPY | 2019-2020 | 20 | bearish | 4 | 4 | -0.024743 | +0.004019 | -0.158010 | +0.050998 | 2 | 2 | 0 | -0.041320 | -0.021639 |
| SPY | 2019-2020 | 20 | neutral | 496 | 10 | +0.016750 | +0.025496 | -0.311755 | +0.234015 | 377 | 119 | 0 | +0.000174 | -0.000162 |
| SPY | 2021-2022 | 1 | all | 503 | 1 | +0.000132 | +0.000494 | -0.033573 | +0.047994 | 264 | 238 | 1 |  |  |
| SPY | 2021-2022 | 1 | bullish | 4 | 4 | -0.000884 | -0.002224 | -0.009204 | +0.010115 | 1 | 3 | 0 | -0.001017 | -0.002718 |
| SPY | 2021-2022 | 1 | bearish | 4 | 4 | +0.002666 | +0.005433 | -0.016655 | +0.016455 | 3 | 1 | 0 | +0.002534 | +0.004938 |
| SPY | 2021-2022 | 1 | neutral | 495 | 9 | +0.000120 | +0.000494 | -0.033573 | +0.047994 | 260 | 234 | 1 | -0.000012 | +0.000000 |
| SPY | 2021-2022 | 5 | all | 503 | 1 | +0.000567 | +0.003218 | -0.096780 | +0.067221 | 273 | 230 | 0 |  |  |
| SPY | 2021-2022 | 5 | bullish | 4 | 4 | -0.003690 | +0.000485 | -0.033610 | +0.017880 | 2 | 2 | 0 | -0.004257 | -0.002733 |
| SPY | 2021-2022 | 5 | bearish | 4 | 4 | -0.008111 | -0.009808 | -0.040577 | +0.027750 | 2 | 2 | 0 | -0.008678 | -0.013026 |
| SPY | 2021-2022 | 5 | neutral | 495 | 9 | +0.000672 | +0.003343 | -0.096780 | +0.067221 | 269 | 226 | 0 | +0.000105 | +0.000125 |
| SPY | 2021-2022 | 20 | all | 503 | 1 | +0.002871 | +0.010213 | -0.126366 | +0.124140 | 297 | 206 | 0 |  |  |
| SPY | 2021-2022 | 20 | bullish | 4 | 4 | -0.024918 | -0.011847 | -0.085321 | +0.009342 | 2 | 2 | 0 | -0.027789 | -0.022060 |
| SPY | 2021-2022 | 20 | bearish | 4 | 4 | -0.012149 | -0.023801 | -0.064433 | +0.063437 | 1 | 3 | 0 | -0.015021 | -0.034014 |
| SPY | 2021-2022 | 20 | neutral | 495 | 9 | +0.003217 | +0.011107 | -0.126366 | +0.124140 | 294 | 201 | 0 | +0.000346 | +0.000894 |
| SPY | 2023-2024 | 1 | all | 502 | 1 | +0.000391 | +0.000653 | -0.029306 | +0.024016 | 282 | 220 | 0 |  |  |
| SPY | 2023-2024 | 1 | bullish | 5 | 5 | +0.004527 | +0.003807 | +0.000199 | +0.013337 | 5 | 0 | 0 | +0.004137 | +0.003154 |
| SPY | 2023-2024 | 1 | bearish | 5 | 5 | +0.005404 | +0.003772 | -0.001760 | +0.014707 | 4 | 1 | 0 | +0.005013 | +0.003119 |
| SPY | 2023-2024 | 1 | neutral | 492 | 10 | +0.000298 | +0.000617 | -0.029306 | +0.024016 | 273 | 219 | 0 | -0.000093 | -0.000036 |
| SPY | 2023-2024 | 5 | all | 502 | 1 | +0.003949 | +0.005523 | -0.061368 | +0.051093 | 313 | 189 | 0 |  |  |
| SPY | 2023-2024 | 5 | bullish | 5 | 5 | +0.004715 | +0.001001 | -0.002563 | +0.021689 | 3 | 2 | 0 | +0.000766 | -0.004522 |
| SPY | 2023-2024 | 5 | bearish | 5 | 5 | +0.020592 | +0.019312 | -0.002607 | +0.037626 | 4 | 1 | 0 | +0.016643 | +0.013789 |
| SPY | 2023-2024 | 5 | neutral | 492 | 10 | +0.003772 | +0.005523 | -0.061368 | +0.051093 | 306 | 186 | 0 | -0.000177 | +0.000000 |
| SPY | 2023-2024 | 20 | all | 502 | 1 | +0.016526 | +0.021535 | -0.076197 | +0.101712 | 366 | 136 | 0 |  |  |
| SPY | 2023-2024 | 20 | bullish | 5 | 5 | +0.020707 | +0.033479 | -0.012141 | +0.047796 | 3 | 2 | 0 | +0.004181 | +0.011944 |
| SPY | 2023-2024 | 20 | bearish | 5 | 5 | +0.030637 | +0.038728 | -0.037885 | +0.072081 | 4 | 1 | 0 | +0.014111 | +0.017193 |
| SPY | 2023-2024 | 20 | neutral | 492 | 10 | +0.016340 | +0.021320 | -0.076197 | +0.101712 | 359 | 133 | 0 | -0.000186 | -0.000216 |
| QQQ | 2015-2016 | 1 | all | 504 | 1 | +0.000157 | +0.000554 | -0.038993 | +0.044890 | 263 | 238 | 3 |  |  |
| QQQ | 2015-2016 | 1 | bullish | 8 | 8 | +0.000419 | +0.000491 | -0.003920 | +0.005467 | 4 | 4 | 0 | +0.000263 | -0.000063 |
| QQQ | 2015-2016 | 1 | bearish | 8 | 8 | +0.002069 | +0.000044 | -0.009651 | +0.020503 | 4 | 4 | 0 | +0.001912 | -0.000510 |
| QQQ | 2015-2016 | 1 | neutral | 488 | 17 | +0.000121 | +0.000554 | -0.038993 | +0.044890 | 255 | 230 | 3 | -0.000036 | +0.000000 |
| QQQ | 2015-2016 | 5 | all | 504 | 1 | +0.001794 | +0.003123 | -0.115205 | +0.120874 | 294 | 210 | 0 |  |  |
| QQQ | 2015-2016 | 5 | bullish | 8 | 8 | +0.002187 | +0.006835 | -0.018094 | +0.016093 | 6 | 2 | 0 | +0.000392 | +0.003712 |
| QQQ | 2015-2016 | 5 | bearish | 8 | 8 | -0.008194 | -0.001870 | -0.070878 | +0.037545 | 4 | 4 | 0 | -0.009989 | -0.004993 |
| QQQ | 2015-2016 | 5 | neutral | 488 | 17 | +0.001952 | +0.003283 | -0.115205 | +0.120874 | 284 | 204 | 0 | +0.000157 | +0.000160 |
| QQQ | 2015-2016 | 20 | all | 504 | 1 | +0.008176 | +0.011022 | -0.119242 | +0.129365 | 317 | 186 | 1 |  |  |
| QQQ | 2015-2016 | 20 | bullish | 8 | 8 | +0.003214 | +0.018820 | -0.119242 | +0.043478 | 6 | 2 | 0 | -0.004962 | +0.007799 |
| QQQ | 2015-2016 | 20 | bearish | 8 | 8 | +0.014151 | +0.029106 | -0.077434 | +0.064022 | 6 | 2 | 0 | +0.005975 | +0.018085 |
| QQQ | 2015-2016 | 20 | neutral | 488 | 17 | +0.008159 | +0.010459 | -0.119148 | +0.129365 | 305 | 182 | 1 | -0.000017 | -0.000563 |
| QQQ | 2017-2018 | 1 | all | 502 | 1 | -0.000000 | +0.000634 | -0.044664 | +0.050869 | 274 | 225 | 3 |  |  |
| QQQ | 2017-2018 | 1 | bullish | 2 | 2 | +0.003027 | +0.003027 | +0.000760 | +0.005295 | 2 | 0 | 0 | +0.003028 | +0.002393 |
| QQQ | 2017-2018 | 1 | bearish | 3 | 3 | -0.005640 | -0.008635 | -0.014162 | +0.005876 | 1 | 2 | 0 | -0.005640 | -0.009269 |
| QQQ | 2017-2018 | 1 | neutral | 497 | 6 | +0.000021 | +0.000615 | -0.044664 | +0.050869 | 271 | 223 | 3 | +0.000022 | -0.000019 |
| QQQ | 2017-2018 | 5 | all | 502 | 1 | +0.002217 | +0.004826 | -0.095493 | +0.067549 | 306 | 194 | 2 |  |  |
| QQQ | 2017-2018 | 5 | bullish | 2 | 2 | -0.003877 | -0.003877 | -0.008290 | +0.000535 | 1 | 1 | 0 | -0.006094 | -0.008703 |
| QQQ | 2017-2018 | 5 | bearish | 3 | 3 | +0.015988 | +0.020959 | -0.003972 | +0.030976 | 2 | 1 | 0 | +0.013771 | +0.016133 |
| QQQ | 2017-2018 | 5 | neutral | 497 | 6 | +0.002158 | +0.004947 | -0.095493 | +0.067549 | 303 | 192 | 2 | -0.000059 | +0.000121 |
| QQQ | 2017-2018 | 20 | all | 502 | 1 | +0.010890 | +0.015325 | -0.126057 | +0.124897 | 347 | 155 | 0 |  |  |
| QQQ | 2017-2018 | 20 | bullish | 2 | 2 | +0.017605 | +0.017605 | -0.010776 | +0.045987 | 1 | 1 | 0 | +0.006716 | +0.002281 |
| QQQ | 2017-2018 | 20 | bearish | 3 | 3 | +0.015949 | +0.018379 | -0.012607 | +0.042075 | 2 | 1 | 0 | +0.005059 | +0.003054 |
| QQQ | 2017-2018 | 20 | neutral | 497 | 6 | +0.010832 | +0.015258 | -0.126057 | +0.124897 | 344 | 153 | 0 | -0.000058 | -0.000067 |
| QQQ | 2019-2020 | 1 | all | 505 | 1 | +0.000669 | +0.001106 | -0.060746 | +0.043672 | 278 | 225 | 2 |  |  |
| QQQ | 2019-2020 | 1 | bullish | 5 | 5 | -0.007207 | +0.000735 | -0.026781 | +0.008758 | 3 | 2 | 0 | -0.007876 | -0.000371 |
| QQQ | 2019-2020 | 1 | bearish | 4 | 4 | -0.008555 | -0.005731 | -0.020717 | -0.002041 | 0 | 4 | 0 | -0.009224 | -0.006837 |
| QQQ | 2019-2020 | 1 | neutral | 496 | 10 | +0.000823 | +0.001276 | -0.060746 | +0.043672 | 275 | 219 | 2 | +0.000154 | +0.000170 |
| QQQ | 2019-2020 | 5 | all | 505 | 1 | +0.006601 | +0.008288 | -0.158172 | +0.106654 | 322 | 183 | 0 |  |  |
| QQQ | 2019-2020 | 5 | bullish | 5 | 5 | -0.003264 | -0.009663 | -0.019794 | +0.022915 | 2 | 3 | 0 | -0.009864 | -0.017951 |
| QQQ | 2019-2020 | 5 | bearish | 4 | 4 | -0.022975 | -0.012548 | -0.086331 | +0.019528 | 1 | 3 | 0 | -0.029576 | -0.020836 |
| QQQ | 2019-2020 | 5 | neutral | 496 | 10 | +0.006939 | +0.008421 | -0.158172 | +0.106654 | 319 | 177 | 0 | +0.000338 | +0.000133 |
| QQQ | 2019-2020 | 20 | all | 505 | 1 | +0.028637 | +0.039792 | -0.274946 | +0.244676 | 397 | 108 | 0 |  |  |
| QQQ | 2019-2020 | 20 | bullish | 5 | 5 | +0.025114 | +0.024207 | +0.001515 | +0.053930 | 5 | 0 | 0 | -0.003523 | -0.015584 |
| QQQ | 2019-2020 | 20 | bearish | 4 | 4 | +0.014911 | +0.013013 | -0.014798 | +0.048415 | 3 | 1 | 0 | -0.013726 | -0.026778 |
| QQQ | 2019-2020 | 20 | neutral | 496 | 10 | +0.028783 | +0.040133 | -0.274946 | +0.244676 | 389 | 107 | 0 | +0.000146 | +0.000342 |
| QQQ | 2021-2022 | 1 | all | 503 | 1 | -0.000036 | +0.000660 | -0.040090 | +0.067902 | 263 | 240 | 0 |  |  |
| QQQ | 2021-2022 | 1 | bullish | 6 | 6 | +0.005074 | +0.010515 | -0.012733 | +0.015795 | 4 | 2 | 0 | +0.005110 | +0.009855 |
| QQQ | 2021-2022 | 1 | bearish | 7 | 7 | +0.000048 | +0.005098 | -0.032283 | +0.015787 | 4 | 3 | 0 | +0.000085 | +0.004438 |
| QQQ | 2021-2022 | 1 | neutral | 490 | 14 | -0.000100 | +0.000599 | -0.040090 | +0.067902 | 255 | 235 | 0 | -0.000064 | -0.000061 |
| QQQ | 2021-2022 | 5 | all | 503 | 1 | -0.000870 | +0.000545 | -0.107232 | +0.091000 | 257 | 246 | 0 |  |  |
| QQQ | 2021-2022 | 5 | bullish | 6 | 6 | +0.002258 | +0.003744 | -0.045550 | +0.041780 | 3 | 3 | 0 | +0.003127 | +0.003199 |
| QQQ | 2021-2022 | 5 | bearish | 7 | 7 | -0.006208 | -0.005799 | -0.035740 | +0.019649 | 3 | 4 | 0 | -0.005338 | -0.006344 |
| QQQ | 2021-2022 | 5 | neutral | 490 | 14 | -0.000832 | +0.000547 | -0.107232 | +0.091000 | 251 | 239 | 0 | +0.000038 | +0.000002 |
| QQQ | 2021-2022 | 20 | all | 503 | 1 | -0.002782 | +0.001216 | -0.159595 | +0.151737 | 254 | 249 | 0 |  |  |
| QQQ | 2021-2022 | 20 | bullish | 6 | 6 | -0.013578 | -0.025915 | -0.073246 | +0.060446 | 2 | 4 | 0 | -0.010796 | -0.027131 |
| QQQ | 2021-2022 | 20 | bearish | 7 | 7 | +0.012559 | +0.048611 | -0.106811 | +0.101092 | 4 | 3 | 0 | +0.015341 | +0.047395 |
| QQQ | 2021-2022 | 20 | neutral | 490 | 14 | -0.002869 | +0.001317 | -0.159595 | +0.151737 | 248 | 242 | 0 | -0.000087 | +0.000101 |
| QQQ | 2023-2024 | 1 | all | 502 | 1 | +0.000611 | +0.001308 | -0.034906 | +0.029564 | 280 | 222 | 0 |  |  |
| QQQ | 2023-2024 | 1 | bullish | 4 | 4 | +0.006904 | +0.005691 | -0.005879 | +0.022112 | 2 | 2 | 0 | +0.006293 | +0.004383 |
| QQQ | 2023-2024 | 1 | bearish | 3 | 3 | -0.015559 | -0.026249 | -0.030646 | +0.010219 | 1 | 2 | 0 | -0.016170 | -0.027557 |
| QQQ | 2023-2024 | 1 | neutral | 495 | 8 | +0.000658 | +0.001326 | -0.034906 | +0.029564 | 277 | 218 | 0 | +0.000047 | +0.000018 |
| QQQ | 2023-2024 | 5 | all | 502 | 1 | +0.006171 | +0.006639 | -0.078409 | +0.067534 | 314 | 188 | 0 |  |  |
| QQQ | 2023-2024 | 5 | bullish | 4 | 4 | +0.018908 | +0.011127 | +0.000833 | +0.052546 | 4 | 0 | 0 | +0.012738 | +0.004488 |
| QQQ | 2023-2024 | 5 | bearish | 3 | 3 | +0.025278 | +0.028472 | +0.011325 | +0.036037 | 3 | 0 | 0 | +0.019107 | +0.021833 |
| QQQ | 2023-2024 | 5 | neutral | 495 | 8 | +0.005952 | +0.006341 | -0.078409 | +0.067534 | 307 | 188 | 0 | -0.000219 | -0.000298 |
| QQQ | 2023-2024 | 20 | all | 502 | 1 | +0.025069 | +0.026373 | -0.135766 | +0.180579 | 377 | 124 | 1 |  |  |
| QQQ | 2023-2024 | 20 | bullish | 4 | 4 | +0.035955 | +0.049503 | -0.010903 | +0.055716 | 3 | 1 | 0 | +0.010886 | +0.023130 |
| QQQ | 2023-2024 | 20 | bearish | 3 | 3 | +0.024366 | +0.031624 | -0.039663 | +0.081137 | 2 | 1 | 0 | -0.000703 | +0.005251 |
| QQQ | 2023-2024 | 20 | neutral | 495 | 8 | +0.024985 | +0.026240 | -0.135766 | +0.180579 | 372 | 122 | 1 | -0.000084 | -0.000134 |
| IWM | 2015-2016 | 1 | all | 504 | 1 | +0.000370 | +0.000797 | -0.038229 | +0.037771 | 271 | 232 | 1 |  |  |
| IWM | 2015-2016 | 1 | bullish | 5 | 5 | +0.002972 | +0.005147 | -0.007452 | +0.013203 | 3 | 2 | 0 | +0.002602 | +0.004350 |
| IWM | 2015-2016 | 1 | bearish | 5 | 5 | +0.001598 | +0.005512 | -0.011361 | +0.006735 | 4 | 1 | 0 | +0.001228 | +0.004714 |
| IWM | 2015-2016 | 1 | neutral | 494 | 11 | +0.000331 | +0.000741 | -0.038229 | +0.037771 | 264 | 229 | 1 | -0.000039 | -0.000056 |
| IWM | 2015-2016 | 5 | all | 504 | 1 | +0.001830 | +0.003833 | -0.089906 | +0.097138 | 284 | 219 | 1 |  |  |
| IWM | 2015-2016 | 5 | bullish | 5 | 5 | +0.012267 | +0.013277 | +0.001060 | +0.017839 | 5 | 0 | 0 | +0.010437 | +0.009444 |
| IWM | 2015-2016 | 5 | bearish | 5 | 5 | +0.004823 | +0.016047 | -0.024402 | +0.031777 | 3 | 2 | 0 | +0.002993 | +0.012214 |
| IWM | 2015-2016 | 5 | neutral | 494 | 11 | +0.001694 | +0.003276 | -0.089906 | +0.097138 | 276 | 217 | 1 | -0.000136 | -0.000557 |
| IWM | 2015-2016 | 20 | all | 504 | 1 | +0.006931 | +0.010016 | -0.133869 | +0.150915 | 291 | 213 | 0 |  |  |
| IWM | 2015-2016 | 20 | bullish | 5 | 5 | +0.016494 | +0.020815 | -0.023533 | +0.044202 | 4 | 1 | 0 | +0.009563 | +0.010799 |
| IWM | 2015-2016 | 20 | bearish | 5 | 5 | +0.002515 | +0.026243 | -0.115806 | +0.083486 | 3 | 2 | 0 | -0.004416 | +0.016227 |
| IWM | 2015-2016 | 20 | neutral | 494 | 11 | +0.006879 | +0.009382 | -0.133869 | +0.150915 | 284 | 210 | 0 | -0.000052 | -0.000634 |
| IWM | 2017-2018 | 1 | all | 502 | 1 | -0.000398 | +0.000165 | -0.040520 | +0.044742 | 255 | 244 | 3 |  |  |
| IWM | 2017-2018 | 1 | bullish | 6 | 6 | +0.002754 | +0.003922 | -0.005663 | +0.010131 | 4 | 2 | 0 | +0.003152 | +0.003757 |
| IWM | 2017-2018 | 1 | bearish | 7 | 7 | +0.001625 | +0.000309 | -0.003081 | +0.011245 | 5 | 2 | 0 | +0.002023 | +0.000144 |
| IWM | 2017-2018 | 1 | neutral | 489 | 14 | -0.000466 | +0.000068 | -0.040520 | +0.044742 | 246 | 240 | 3 | -0.000068 | -0.000097 |
| IWM | 2017-2018 | 5 | all | 502 | 1 | -0.000111 | +0.000517 | -0.089541 | +0.072331 | 258 | 243 | 1 |  |  |
| IWM | 2017-2018 | 5 | bullish | 6 | 6 | +0.004551 | +0.009162 | -0.045301 | +0.028955 | 4 | 2 | 0 | +0.004661 | +0.008645 |
| IWM | 2017-2018 | 5 | bearish | 7 | 7 | -0.000031 | +0.010233 | -0.050504 | +0.016468 | 5 | 2 | 0 | +0.000080 | +0.009716 |
| IWM | 2017-2018 | 5 | neutral | 489 | 14 | -0.000169 | +0.000401 | -0.089541 | +0.072331 | 249 | 239 | 1 | -0.000058 | -0.000116 |
| IWM | 2017-2018 | 20 | all | 502 | 1 | +0.002655 | +0.006580 | -0.156978 | +0.151964 | 301 | 200 | 1 |  |  |
| IWM | 2017-2018 | 20 | bullish | 6 | 6 | +0.011689 | -0.004420 | -0.015669 | +0.066979 | 2 | 4 | 0 | +0.009034 | -0.010999 |
| IWM | 2017-2018 | 20 | bearish | 7 | 7 | +0.010806 | +0.024451 | -0.048031 | +0.044608 | 5 | 2 | 0 | +0.008151 | +0.017871 |
| IWM | 2017-2018 | 20 | neutral | 489 | 14 | +0.002428 | +0.006681 | -0.156978 | +0.151964 | 294 | 194 | 1 | -0.000228 | +0.000101 |
| IWM | 2019-2020 | 1 | all | 505 | 1 | -0.000196 | +0.000389 | -0.046032 | +0.057848 | 259 | 243 | 3 |  |  |
| IWM | 2019-2020 | 1 | bullish | 6 | 6 | -0.001811 | -0.001886 | -0.017531 | +0.009823 | 3 | 3 | 0 | -0.001615 | -0.002275 |
| IWM | 2019-2020 | 1 | bearish | 5 | 5 | -0.007133 | -0.003359 | -0.038211 | +0.020706 | 1 | 4 | 0 | -0.006937 | -0.003748 |
| IWM | 2019-2020 | 1 | neutral | 494 | 12 | -0.000106 | +0.000513 | -0.046032 | +0.057848 | 255 | 236 | 3 | +0.000090 | +0.000124 |
| IWM | 2019-2020 | 5 | all | 505 | 1 | +0.003653 | +0.005608 | -0.230792 | +0.160709 | 298 | 207 | 0 |  |  |
| IWM | 2019-2020 | 5 | bullish | 6 | 6 | -0.005445 | -0.003794 | -0.036659 | +0.022492 | 3 | 3 | 0 | -0.009097 | -0.009402 |
| IWM | 2019-2020 | 5 | bearish | 5 | 5 | +0.003077 | +0.008174 | -0.070699 | +0.060931 | 4 | 1 | 0 | -0.000575 | +0.002565 |
| IWM | 2019-2020 | 5 | neutral | 494 | 12 | +0.003769 | +0.005496 | -0.230792 | +0.160709 | 291 | 203 | 0 | +0.000116 | -0.000112 |
| IWM | 2019-2020 | 20 | all | 505 | 1 | +0.018300 | +0.024820 | -0.404586 | +0.246182 | 345 | 160 | 0 |  |  |
| IWM | 2019-2020 | 20 | bullish | 6 | 6 | +0.048375 | +0.052618 | -0.042319 | +0.135018 | 4 | 2 | 0 | +0.030075 | +0.027799 |
| IWM | 2019-2020 | 20 | bearish | 5 | 5 | -0.028902 | +0.033806 | -0.385306 | +0.130298 | 4 | 1 | 0 | -0.047202 | +0.008987 |
| IWM | 2019-2020 | 20 | neutral | 494 | 12 | +0.018412 | +0.024652 | -0.404586 | +0.246182 | 337 | 157 | 0 | +0.000112 | -0.000168 |
| IWM | 2021-2022 | 1 | all | 503 | 1 | -0.000521 | -0.000269 | -0.044406 | +0.051614 | 245 | 258 | 0 |  |  |
| IWM | 2021-2022 | 1 | bullish | 7 | 7 | +0.002580 | +0.001208 | -0.012389 | +0.019412 | 4 | 3 | 0 | +0.003102 | +0.001477 |
| IWM | 2021-2022 | 1 | bearish | 8 | 8 | -0.001175 | -0.003877 | -0.013275 | +0.014132 | 3 | 5 | 0 | -0.000654 | -0.003608 |
| IWM | 2021-2022 | 1 | neutral | 488 | 16 | -0.000555 | -0.000264 | -0.044406 | +0.051614 | 238 | 250 | 0 | -0.000034 | +0.000005 |
| IWM | 2021-2022 | 5 | all | 503 | 1 | -0.001259 | -0.001305 | -0.109278 | +0.084537 | 245 | 258 | 0 |  |  |
| IWM | 2021-2022 | 5 | bullish | 7 | 7 | +0.001648 | -0.000433 | -0.036604 | +0.034054 | 3 | 4 | 0 | +0.002907 | +0.000872 |
| IWM | 2021-2022 | 5 | bearish | 8 | 8 | -0.017004 | -0.004220 | -0.081669 | +0.006699 | 3 | 5 | 0 | -0.015745 | -0.002915 |
| IWM | 2021-2022 | 5 | neutral | 488 | 16 | -0.001043 | -0.001283 | -0.109278 | +0.084537 | 239 | 249 | 0 | +0.000216 | +0.000023 |
| IWM | 2021-2022 | 20 | all | 503 | 1 | -0.003887 | -0.002359 | -0.143493 | +0.159711 | 245 | 258 | 0 |  |  |
| IWM | 2021-2022 | 20 | bullish | 7 | 7 | -0.019312 | -0.016418 | -0.097404 | +0.055624 | 2 | 5 | 0 | -0.015425 | -0.014058 |
| IWM | 2021-2022 | 20 | bearish | 8 | 8 | +0.005212 | -0.020352 | -0.064475 | +0.077236 | 3 | 5 | 0 | +0.009100 | -0.017993 |
| IWM | 2021-2022 | 20 | neutral | 488 | 16 | -0.003815 | -0.001183 | -0.143493 | +0.159711 | 240 | 248 | 0 | +0.000072 | +0.001176 |
| IWM | 2023-2024 | 1 | all | 502 | 1 | -0.000154 | +0.000083 | -0.049087 | +0.033298 | 252 | 250 | 0 |  |  |
| IWM | 2023-2024 | 1 | bullish | 5 | 5 | -0.003357 | -0.002856 | -0.015627 | +0.008512 | 2 | 3 | 0 | -0.003203 | -0.002939 |
| IWM | 2023-2024 | 1 | bearish | 5 | 5 | +0.006705 | +0.005612 | -0.008029 | +0.026302 | 3 | 2 | 0 | +0.006860 | +0.005530 |
| IWM | 2023-2024 | 1 | neutral | 492 | 10 | -0.000191 | +0.000083 | -0.049087 | +0.033298 | 247 | 245 | 0 | -0.000037 | +0.000000 |
| IWM | 2023-2024 | 5 | all | 502 | 1 | +0.002091 | +0.000601 | -0.097377 | +0.110287 | 258 | 244 | 0 |  |  |
| IWM | 2023-2024 | 5 | bullish | 5 | 5 | +0.018718 | +0.020799 | -0.016079 | +0.055006 | 3 | 2 | 0 | +0.016626 | +0.020198 |
| IWM | 2023-2024 | 5 | bearish | 5 | 5 | +0.001815 | +0.000991 | -0.014764 | +0.021369 | 3 | 2 | 0 | -0.000276 | +0.000391 |
| IWM | 2023-2024 | 5 | neutral | 492 | 10 | +0.001925 | +0.000538 | -0.097377 | +0.110287 | 252 | 240 | 0 | -0.000166 | -0.000063 |
| IWM | 2023-2024 | 20 | all | 502 | 1 | +0.008755 | +0.007829 | -0.107619 | +0.143097 | 280 | 222 | 0 |  |  |
| IWM | 2023-2024 | 20 | bullish | 5 | 5 | +0.015051 | -0.002500 | -0.066528 | +0.143097 | 2 | 3 | 0 | +0.006296 | -0.010329 |
| IWM | 2023-2024 | 20 | bearish | 5 | 5 | +0.033185 | +0.039074 | -0.060257 | +0.099765 | 4 | 1 | 0 | +0.024430 | +0.031245 |
| IWM | 2023-2024 | 20 | neutral | 492 | 10 | +0.008442 | +0.007397 | -0.107619 | +0.140741 | 274 | 218 | 0 | -0.000312 | -0.000431 |
| TLT | 2015-2016 | 1 | all | 504 | 1 | -0.000099 | +0.000115 | -0.020830 | +0.015824 | 254 | 248 | 2 |  |  |
| TLT | 2015-2016 | 1 | bullish | 6 | 6 | -0.002479 | -0.001860 | -0.011003 | +0.003465 | 1 | 5 | 0 | -0.002380 | -0.001975 |
| TLT | 2015-2016 | 1 | bearish | 7 | 7 | +0.001609 | +0.002105 | -0.003783 | +0.008296 | 4 | 3 | 0 | +0.001708 | +0.001990 |
| TLT | 2015-2016 | 1 | neutral | 491 | 14 | -0.000094 | +0.000153 | -0.020830 | +0.015824 | 249 | 240 | 2 | +0.000005 | +0.000038 |
| TLT | 2015-2016 | 5 | all | 504 | 1 | -0.000546 | +0.000506 | -0.074111 | +0.045586 | 261 | 242 | 1 |  |  |
| TLT | 2015-2016 | 5 | bullish | 6 | 6 | -0.002560 | +0.000771 | -0.020302 | +0.003630 | 4 | 2 | 0 | -0.002014 | +0.000265 |
| TLT | 2015-2016 | 5 | bearish | 7 | 7 | -0.002349 | -0.005988 | -0.027104 | +0.017951 | 3 | 4 | 0 | -0.001803 | -0.006494 |
| TLT | 2015-2016 | 5 | neutral | 491 | 14 | -0.000496 | +0.000527 | -0.074111 | +0.045586 | 254 | 236 | 1 | +0.000050 | +0.000021 |
| TLT | 2015-2016 | 20 | all | 504 | 1 | -0.003200 | +0.001017 | -0.094146 | +0.078670 | 256 | 248 | 0 |  |  |
| TLT | 2015-2016 | 20 | bullish | 6 | 6 | -0.010576 | +0.002131 | -0.078780 | +0.027468 | 3 | 3 | 0 | -0.007376 | +0.001114 |
| TLT | 2015-2016 | 20 | bearish | 7 | 7 | +0.006898 | +0.017704 | -0.027837 | +0.027741 | 5 | 2 | 0 | +0.010098 | +0.016688 |
| TLT | 2015-2016 | 20 | neutral | 491 | 14 | -0.003254 | +0.000458 | -0.094146 | +0.078670 | 248 | 243 | 0 | -0.000054 | -0.000559 |
| TLT | 2017-2018 | 1 | all | 502 | 1 | +0.000228 | +0.000161 | -0.014533 | +0.012923 | 258 | 238 | 6 |  |  |
| TLT | 2017-2018 | 1 | bullish | 8 | 8 | -0.001252 | -0.001803 | -0.009274 | +0.005093 | 3 | 5 | 0 | -0.001481 | -0.001964 |
| TLT | 2017-2018 | 1 | bearish | 7 | 7 | -0.000300 | -0.001429 | -0.006353 | +0.006477 | 3 | 4 | 0 | -0.000529 | -0.001590 |
| TLT | 2017-2018 | 1 | neutral | 487 | 16 | +0.000260 | +0.000162 | -0.014533 | +0.012923 | 252 | 229 | 6 | +0.000032 | +0.000001 |
| TLT | 2017-2018 | 5 | all | 502 | 1 | +0.000360 | +0.000418 | -0.034370 | +0.042203 | 255 | 246 | 1 |  |  |
| TLT | 2017-2018 | 5 | bullish | 8 | 8 | -0.000475 | -0.000097 | -0.014260 | +0.013378 | 4 | 4 | 0 | -0.000835 | -0.000515 |
| TLT | 2017-2018 | 5 | bearish | 7 | 7 | +0.005599 | +0.009886 | -0.010672 | +0.013464 | 6 | 1 | 0 | +0.005238 | +0.009468 |
| TLT | 2017-2018 | 5 | neutral | 487 | 16 | +0.000299 | +0.000246 | -0.034370 | +0.042203 | 245 | 241 | 1 | -0.000062 | -0.000172 |
| TLT | 2017-2018 | 20 | all | 502 | 1 | +0.000533 | +0.000976 | -0.053913 | +0.065138 | 260 | 242 | 0 |  |  |
| TLT | 2017-2018 | 20 | bullish | 8 | 8 | -0.005558 | -0.007180 | -0.041166 | +0.033444 | 2 | 6 | 0 | -0.006091 | -0.008156 |
| TLT | 2017-2018 | 20 | bearish | 7 | 7 | +0.002694 | +0.008401 | -0.039025 | +0.034430 | 5 | 2 | 0 | +0.002161 | +0.007425 |
| TLT | 2017-2018 | 20 | neutral | 487 | 16 | +0.000602 | +0.000992 | -0.053913 | +0.065138 | 253 | 234 | 0 | +0.000069 | +0.000016 |
| TLT | 2019-2020 | 1 | all | 505 | 1 | -0.000097 | +0.000082 | -0.064343 | +0.053968 | 257 | 245 | 3 |  |  |
| TLT | 2019-2020 | 1 | bullish | 5 | 5 | +0.001290 | +0.002643 | -0.005350 | +0.008338 | 3 | 2 | 0 | +0.001387 | +0.002561 |
| TLT | 2019-2020 | 1 | bearish | 6 | 6 | +0.003618 | +0.004027 | -0.000873 | +0.007721 | 5 | 1 | 0 | +0.003715 | +0.003945 |
| TLT | 2019-2020 | 1 | neutral | 494 | 11 | -0.000156 | +0.000066 | -0.064343 | +0.053968 | 249 | 242 | 3 | -0.000059 | -0.000016 |
| TLT | 2019-2020 | 5 | all | 505 | 1 | +0.001886 | +0.001520 | -0.140480 | +0.113647 | 283 | 221 | 1 |  |  |
| TLT | 2019-2020 | 5 | bullish | 5 | 5 | +0.011578 | +0.011186 | -0.012734 | +0.032786 | 4 | 1 | 0 | +0.009692 | +0.009666 |
| TLT | 2019-2020 | 5 | bearish | 6 | 6 | -0.001933 | +0.002500 | -0.033680 | +0.026532 | 3 | 3 | 0 | -0.003819 | +0.000980 |
| TLT | 2019-2020 | 5 | neutral | 494 | 11 | +0.001834 | +0.001445 | -0.140480 | +0.113647 | 276 | 217 | 1 | -0.000052 | -0.000075 |
| TLT | 2019-2020 | 20 | all | 505 | 1 | +0.009335 | +0.002346 | -0.065179 | +0.180496 | 267 | 238 | 0 |  |  |
| TLT | 2019-2020 | 20 | bullish | 5 | 5 | +0.018283 | +0.015608 | -0.010547 | +0.049469 | 4 | 1 | 0 | +0.008948 | +0.013262 |
| TLT | 2019-2020 | 20 | bearish | 6 | 6 | +0.011370 | +0.011864 | -0.028277 | +0.049840 | 5 | 1 | 0 | +0.002036 | +0.009518 |
| TLT | 2019-2020 | 20 | neutral | 494 | 11 | +0.009219 | +0.001894 | -0.065179 | +0.180496 | 258 | 236 | 0 | -0.000115 | -0.000452 |
| TLT | 2021-2022 | 1 | all | 503 | 1 | +0.000088 | +0.000359 | -0.024099 | +0.030152 | 263 | 238 | 2 |  |  |
| TLT | 2021-2022 | 1 | bullish | 5 | 5 | -0.001483 | +0.000000 | -0.011610 | +0.005617 | 2 | 2 | 1 | -0.001571 | -0.000359 |
| TLT | 2021-2022 | 1 | bearish | 4 | 4 | -0.000656 | -0.000174 | -0.007188 | +0.004909 | 2 | 2 | 0 | -0.000744 | -0.000533 |
| TLT | 2021-2022 | 1 | neutral | 494 | 10 | +0.000110 | +0.000367 | -0.024099 | +0.030152 | 259 | 234 | 1 | +0.000022 | +0.000007 |
| TLT | 2021-2022 | 5 | all | 503 | 1 | -0.002776 | -0.002440 | -0.061638 | +0.061270 | 236 | 267 | 0 |  |  |
| TLT | 2021-2022 | 5 | bullish | 5 | 5 | +0.007110 | +0.005685 | +0.004630 | +0.010180 | 5 | 0 | 0 | +0.009887 | +0.008126 |
| TLT | 2021-2022 | 5 | bearish | 4 | 4 | -0.006142 | -0.002740 | -0.031059 | +0.011972 | 2 | 2 | 0 | -0.003365 | -0.000300 |
| TLT | 2021-2022 | 5 | neutral | 494 | 10 | -0.002849 | -0.003098 | -0.061638 | +0.061270 | 229 | 265 | 0 | -0.000073 | -0.000658 |
| TLT | 2021-2022 | 20 | all | 503 | 1 | -0.012513 | -0.014320 | -0.115699 | +0.166809 | 201 | 302 | 0 |  |  |
| TLT | 2021-2022 | 20 | bullish | 5 | 5 | -0.008246 | +0.001083 | -0.052162 | +0.029654 | 3 | 2 | 0 | +0.004266 | +0.015403 |
| TLT | 2021-2022 | 20 | bearish | 4 | 4 | -0.010410 | -0.004224 | -0.074186 | +0.040995 | 2 | 2 | 0 | +0.002103 | +0.010096 |
| TLT | 2021-2022 | 20 | neutral | 494 | 10 | -0.012573 | -0.014962 | -0.115699 | +0.166809 | 196 | 298 | 0 | -0.000060 | -0.000642 |
| TLT | 2023-2024 | 1 | all | 502 | 1 | +0.000303 | +0.000115 | -0.022487 | +0.024148 | 255 | 244 | 3 |  |  |
| TLT | 2023-2024 | 1 | bullish | 4 | 4 | +0.009725 | +0.010137 | +0.007554 | +0.011074 | 4 | 0 | 0 | +0.009422 | +0.010022 |
| TLT | 2023-2024 | 1 | bearish | 5 | 5 | +0.000509 | -0.001425 | -0.004633 | +0.008328 | 2 | 3 | 0 | +0.000206 | -0.001540 |
| TLT | 2023-2024 | 1 | neutral | 493 | 10 | +0.000224 | +0.000107 | -0.022487 | +0.024148 | 249 | 241 | 3 | -0.000079 | -0.000009 |
| TLT | 2023-2024 | 5 | all | 502 | 1 | -0.001006 | -0.001293 | -0.055137 | +0.054675 | 239 | 263 | 0 |  |  |
| TLT | 2023-2024 | 5 | bullish | 4 | 4 | +0.012126 | +0.019639 | -0.020960 | +0.030185 | 3 | 1 | 0 | +0.013132 | +0.020932 |
| TLT | 2023-2024 | 5 | bearish | 5 | 5 | -0.010853 | -0.019322 | -0.025831 | +0.010629 | 2 | 3 | 0 | -0.009847 | -0.018029 |
| TLT | 2023-2024 | 5 | neutral | 493 | 10 | -0.001012 | -0.001300 | -0.055137 | +0.054675 | 234 | 259 | 0 | -0.000007 | -0.000007 |
| TLT | 2023-2024 | 20 | all | 502 | 1 | -0.006346 | -0.007974 | -0.095972 | +0.109071 | 215 | 287 | 0 |  |  |
| TLT | 2023-2024 | 20 | bullish | 4 | 4 | +0.008399 | +0.001241 | -0.059474 | +0.090587 | 2 | 2 | 0 | +0.014745 | +0.009216 |
| TLT | 2023-2024 | 20 | bearish | 5 | 5 | -0.011376 | -0.023000 | -0.033311 | +0.048896 | 1 | 4 | 0 | -0.005030 | -0.015025 |
| TLT | 2023-2024 | 20 | neutral | 493 | 10 | -0.006414 | -0.007634 | -0.095972 | +0.109071 | 212 | 281 | 0 | -0.000069 | +0.000340 |
| GLD | 2015-2016 | 1 | all | 504 | 1 | -0.000231 | -0.000337 | -0.022290 | +0.026997 | 232 | 270 | 2 |  |  |
| GLD | 2015-2016 | 1 | bullish | 5 | 5 | -0.002417 | -0.000871 | -0.008006 | +0.001898 | 1 | 4 | 0 | -0.002186 | -0.000534 |
| GLD | 2015-2016 | 1 | bearish | 6 | 6 | -0.000385 | +0.000052 | -0.004912 | +0.002700 | 3 | 3 | 0 | -0.000154 | +0.000389 |
| GLD | 2015-2016 | 1 | neutral | 493 | 12 | -0.000207 | -0.000336 | -0.022290 | +0.026997 | 228 | 263 | 2 | +0.000024 | +0.000000 |
| GLD | 2015-2016 | 5 | all | 504 | 1 | -0.000351 | -0.002281 | -0.057763 | +0.084434 | 231 | 272 | 1 |  |  |
| GLD | 2015-2016 | 5 | bullish | 5 | 5 | -0.003349 | -0.004847 | -0.015415 | +0.015581 | 2 | 3 | 0 | -0.002998 | -0.002566 |
| GLD | 2015-2016 | 5 | bearish | 6 | 6 | -0.000810 | +0.001918 | -0.035074 | +0.034937 | 4 | 2 | 0 | -0.000460 | +0.004199 |
| GLD | 2015-2016 | 5 | neutral | 493 | 12 | -0.000314 | -0.002530 | -0.057763 | +0.084434 | 225 | 267 | 1 | +0.000036 | -0.000249 |
| GLD | 2015-2016 | 20 | all | 504 | 1 | -0.001428 | -0.002064 | -0.100322 | +0.147566 | 240 | 264 | 0 |  |  |
| GLD | 2015-2016 | 20 | bullish | 5 | 5 | +0.017796 | +0.010874 | -0.065923 | +0.128098 | 3 | 2 | 0 | +0.019223 | +0.012938 |
| GLD | 2015-2016 | 20 | bearish | 6 | 6 | +0.010463 | -0.004650 | -0.019735 | +0.092574 | 2 | 4 | 0 | +0.011891 | -0.002586 |
| GLD | 2015-2016 | 20 | neutral | 493 | 12 | -0.001768 | -0.001995 | -0.100322 | +0.147566 | 235 | 258 | 0 | -0.000340 | +0.000068 |
| GLD | 2017-2018 | 1 | all | 502 | 1 | +0.000053 | -0.000085 | -0.013908 | +0.017149 | 244 | 255 | 3 |  |  |
| GLD | 2017-2018 | 1 | bullish | 7 | 7 | +0.000884 | +0.001065 | -0.001033 | +0.001928 | 6 | 1 | 0 | +0.000832 | +0.001150 |
| GLD | 2017-2018 | 1 | bearish | 6 | 6 | +0.000127 | -0.000000 | -0.000964 | +0.001795 | 3 | 3 | 0 | +0.000074 | +0.000085 |
| GLD | 2017-2018 | 1 | neutral | 489 | 14 | +0.000040 | -0.000168 | -0.013908 | +0.017149 | 235 | 251 | 3 | -0.000013 | -0.000083 |
| GLD | 2017-2018 | 5 | all | 502 | 1 | +0.000801 | +0.000166 | -0.033299 | +0.037186 | 254 | 245 | 3 |  |  |
| GLD | 2017-2018 | 5 | bullish | 7 | 7 | +0.000242 | -0.001720 | -0.017402 | +0.021528 | 2 | 5 | 0 | -0.000559 | -0.001886 |
| GLD | 2017-2018 | 5 | bearish | 6 | 6 | -0.004339 | -0.004154 | -0.015830 | +0.003713 | 2 | 4 | 0 | -0.005140 | -0.004320 |
| GLD | 2017-2018 | 5 | neutral | 489 | 14 | +0.000872 | +0.000345 | -0.033299 | +0.037186 | 250 | 236 | 3 | +0.000071 | +0.000180 |
| GLD | 2017-2018 | 20 | all | 502 | 1 | +0.003046 | -0.000040 | -0.059980 | +0.065995 | 250 | 251 | 1 |  |  |
| GLD | 2017-2018 | 20 | bullish | 7 | 7 | +0.006370 | +0.007149 | -0.043002 | +0.049558 | 4 | 3 | 0 | +0.003323 | +0.007189 |
| GLD | 2017-2018 | 20 | bearish | 6 | 6 | +0.013009 | +0.005560 | -0.012294 | +0.057558 | 3 | 3 | 0 | +0.009963 | +0.005599 |
| GLD | 2017-2018 | 20 | neutral | 489 | 14 | +0.002876 | -0.000079 | -0.059980 | +0.065995 | 243 | 245 | 1 | -0.000170 | -0.000040 |
| GLD | 2019-2020 | 1 | all | 505 | 1 | +0.000004 | +0.000323 | -0.041092 | +0.030131 | 264 | 240 | 1 |  |  |
| GLD | 2019-2020 | 1 | bullish | 3 | 3 | -0.002726 | -0.002861 | -0.005627 | +0.000309 | 1 | 2 | 0 | -0.002730 | -0.003184 |
| GLD | 2019-2020 | 1 | bearish | 4 | 4 | +0.002755 | +0.001681 | -0.000774 | +0.008435 | 3 | 1 | 0 | +0.002751 | +0.001358 |
| GLD | 2019-2020 | 1 | neutral | 498 | 8 | -0.000001 | +0.000373 | -0.041092 | +0.030131 | 260 | 237 | 1 | -0.000006 | +0.000050 |
| GLD | 2019-2020 | 5 | all | 505 | 1 | +0.003285 | +0.003539 | -0.096595 | +0.089048 | 305 | 198 | 2 |  |  |
| GLD | 2019-2020 | 5 | bullish | 3 | 3 | +0.001625 | -0.007925 | -0.019716 | +0.032517 | 1 | 2 | 0 | -0.001659 | -0.011464 |
| GLD | 2019-2020 | 5 | bearish | 4 | 4 | +0.012745 | +0.007229 | -0.016380 | +0.052901 | 2 | 2 | 0 | +0.009460 | +0.003690 |
| GLD | 2019-2020 | 5 | neutral | 498 | 8 | +0.003219 | +0.003540 | -0.096595 | +0.089048 | 302 | 194 | 2 | -0.000066 | +0.000001 |
| GLD | 2019-2020 | 20 | all | 505 | 1 | +0.014268 | +0.006860 | -0.116025 | +0.173379 | 286 | 217 | 2 |  |  |
| GLD | 2019-2020 | 20 | bullish | 3 | 3 | +0.027453 | +0.035936 | -0.010878 | +0.057299 | 2 | 1 | 0 | +0.013184 | +0.029076 |
| GLD | 2019-2020 | 20 | bearish | 4 | 4 | +0.022189 | +0.013094 | -0.028726 | +0.091296 | 3 | 1 | 0 | +0.007921 | +0.006234 |
| GLD | 2019-2020 | 20 | neutral | 498 | 8 | +0.014125 | +0.006803 | -0.116025 | +0.173379 | 281 | 215 | 2 | -0.000143 | -0.000057 |
| GLD | 2021-2022 | 1 | all | 503 | 1 | -0.000009 | -0.000115 | -0.029848 | +0.022181 | 247 | 253 | 3 |  |  |
| GLD | 2021-2022 | 1 | bullish | 7 | 7 | -0.000338 | -0.001342 | -0.008761 | +0.009918 | 3 | 4 | 0 | -0.000329 | -0.001227 |
| GLD | 2021-2022 | 1 | bearish | 6 | 6 | +0.000887 | -0.001766 | -0.006514 | +0.011318 | 2 | 4 | 0 | +0.000896 | -0.001651 |
| GLD | 2021-2022 | 1 | neutral | 490 | 14 | -0.000015 | -0.000031 | -0.029848 | +0.022181 | 242 | 245 | 3 | -0.000006 | +0.000084 |
| GLD | 2021-2022 | 5 | all | 503 | 1 | -0.000123 | +0.001745 | -0.059434 | +0.063177 | 267 | 236 | 0 |  |  |
| GLD | 2021-2022 | 5 | bullish | 7 | 7 | -0.008512 | -0.020192 | -0.040608 | +0.033670 | 3 | 4 | 0 | -0.008390 | -0.021937 |
| GLD | 2021-2022 | 5 | bearish | 6 | 6 | +0.001756 | +0.005963 | -0.023148 | +0.026264 | 4 | 2 | 0 | +0.001878 | +0.004218 |
| GLD | 2021-2022 | 5 | neutral | 490 | 14 | -0.000026 | +0.001707 | -0.059434 | +0.063177 | 260 | 230 | 0 | +0.000097 | -0.000038 |
| GLD | 2021-2022 | 20 | all | 503 | 1 | +0.001321 | +0.002315 | -0.092283 | +0.125867 | 262 | 240 | 1 |  |  |
| GLD | 2021-2022 | 20 | bullish | 7 | 7 | -0.006827 | -0.013551 | -0.053116 | +0.056494 | 3 | 4 | 0 | -0.008148 | -0.015867 |
| GLD | 2021-2022 | 20 | bearish | 6 | 6 | -0.004221 | +0.006736 | -0.054965 | +0.027123 | 3 | 3 | 0 | -0.005543 | +0.004421 |
| GLD | 2021-2022 | 20 | neutral | 490 | 14 | +0.001506 | +0.002317 | -0.092283 | +0.125867 | 256 | 233 | 1 | +0.000184 | +0.000001 |
| GLD | 2023-2024 | 1 | all | 502 | 1 | +0.000057 | -0.000054 | -0.022446 | +0.020727 | 243 | 255 | 4 |  |  |
| GLD | 2023-2024 | 1 | bullish | 5 | 5 | +0.002302 | +0.002005 | -0.005349 | +0.012597 | 3 | 2 | 0 | +0.002245 | +0.002059 |
| GLD | 2023-2024 | 1 | bearish | 6 | 6 | +0.000056 | +0.001289 | -0.006968 | +0.005197 | 3 | 3 | 0 | -0.000001 | +0.001344 |
| GLD | 2023-2024 | 1 | neutral | 491 | 12 | +0.000034 | -0.000055 | -0.022446 | +0.020727 | 237 | 250 | 4 | -0.000023 | -0.000000 |
| GLD | 2023-2024 | 5 | all | 502 | 1 | +0.002960 | +0.001381 | -0.048420 | +0.051503 | 264 | 238 | 0 |  |  |
| GLD | 2023-2024 | 5 | bullish | 5 | 5 | -0.002352 | -0.005917 | -0.016190 | +0.011427 | 2 | 3 | 0 | -0.005312 | -0.007298 |
| GLD | 2023-2024 | 5 | bearish | 6 | 6 | -0.004458 | -0.003557 | -0.014551 | +0.007704 | 2 | 4 | 0 | -0.007419 | -0.004938 |
| GLD | 2023-2024 | 5 | neutral | 491 | 12 | +0.003105 | +0.001633 | -0.048420 | +0.051503 | 260 | 231 | 0 | +0.000145 | +0.000251 |
| GLD | 2023-2024 | 20 | all | 502 | 1 | +0.013891 | +0.010051 | -0.063900 | +0.114880 | 312 | 189 | 1 |  |  |
| GLD | 2023-2024 | 20 | bullish | 5 | 5 | +0.020183 | +0.020204 | -0.015040 | +0.060038 | 4 | 1 | 0 | +0.006292 | +0.010154 |
| GLD | 2023-2024 | 20 | bearish | 6 | 6 | +0.015993 | +0.000758 | -0.031289 | +0.073062 | 3 | 3 | 0 | +0.002102 | -0.009292 |
| GLD | 2023-2024 | 20 | neutral | 491 | 12 | +0.013802 | +0.009898 | -0.063900 | +0.114880 | 305 | 185 | 1 | -0.000090 | -0.000153 |

## D4 — Asset-class sign annotation (metadata only; nothing pooled)

| hypothesis | state | h | class | symbol | n | mean delta | median delta | mean sign | median sign |
|---|---|---|---|---|---|---|---|---|---|
| trend_alignment | bullish | 1 | equity | SPY | 1709 | -0.000115 | -0.000043 | - | - |
| trend_alignment | bullish | 1 | equity | QQQ | 1732 | -0.000134 | -0.000128 | - | - |
| trend_alignment | bullish | 1 | equity | IWM | 1580 | -0.000021 | +0.000089 | - | + |
| trend_alignment | bullish | 1 | treasury | TLT | 1161 | -0.000089 | -0.000053 | - | - |
| trend_alignment | bullish | 1 | gold | GLD | 1325 | +0.000096 | +0.000084 | + | + |
| trend_alignment | bullish | 1 | equity | (class signs) | 3 |  |  | --- | --+ |
| trend_alignment | bullish | 1 | gold | (class signs) | 1 |  |  | + | + |
| trend_alignment | bullish | 1 | treasury | (class signs) | 1 |  |  | - | - |
| trend_alignment | bullish | 5 | equity | SPY | 1709 | -0.000430 | -0.000294 | - | - |
| trend_alignment | bullish | 5 | equity | QQQ | 1732 | -0.001434 | -0.001036 | - | - |
| trend_alignment | bullish | 5 | equity | IWM | 1580 | -0.000812 | -0.001156 | - | - |
| trend_alignment | bullish | 5 | treasury | TLT | 1161 | +0.000826 | +0.000537 | + | + |
| trend_alignment | bullish | 5 | gold | GLD | 1325 | +0.000590 | +0.000688 | + | + |
| trend_alignment | bullish | 5 | equity | (class signs) | 3 |  |  | --- | --- |
| trend_alignment | bullish | 5 | gold | (class signs) | 1 |  |  | + | + |
| trend_alignment | bullish | 5 | treasury | (class signs) | 1 |  |  | + | + |
| trend_alignment | bullish | 20 | equity | SPY | 1709 | -0.003127 | -0.001591 | - | - |
| trend_alignment | bullish | 20 | equity | QQQ | 1732 | -0.004828 | -0.002743 | - | - |
| trend_alignment | bullish | 20 | equity | IWM | 1580 | -0.004448 | -0.003593 | - | - |
| trend_alignment | bullish | 20 | treasury | TLT | 1161 | +0.002751 | +0.000049 | + | + |
| trend_alignment | bullish | 20 | gold | GLD | 1325 | +0.001214 | +0.000588 | + | + |
| trend_alignment | bullish | 20 | equity | (class signs) | 3 |  |  | --- | --- |
| trend_alignment | bullish | 20 | gold | (class signs) | 1 |  |  | + | + |
| trend_alignment | bullish | 20 | treasury | (class signs) | 1 |  |  | + | + |
| trend_alignment | bearish | 1 | equity | SPY | 724 | +0.000126 | +0.000063 | + | + |
| trend_alignment | bearish | 1 | equity | QQQ | 722 | +0.000506 | +0.000784 | + | + |
| trend_alignment | bearish | 1 | equity | IWM | 850 | +0.000188 | +0.000006 | + | + |
| trend_alignment | bearish | 1 | treasury | TLT | 1243 | -0.000013 | -0.000038 | - | - |
| trend_alignment | bearish | 1 | gold | GLD | 1099 | -0.000106 | -0.000008 | - | - |
| trend_alignment | bearish | 1 | equity | (class signs) | 3 |  |  | +++ | +++ |
| trend_alignment | bearish | 1 | gold | (class signs) | 1 |  |  | - | - |
| trend_alignment | bearish | 1 | treasury | (class signs) | 1 |  |  | - | - |
| trend_alignment | bearish | 5 | equity | SPY | 724 | +0.001322 | +0.001689 | + | + |
| trend_alignment | bearish | 5 | equity | QQQ | 722 | +0.003561 | +0.004767 | + | + |
| trend_alignment | bearish | 5 | equity | IWM | 850 | +0.001431 | +0.002319 | + | + |
| trend_alignment | bearish | 5 | treasury | TLT | 1243 | -0.000892 | -0.000633 | - | - |
| trend_alignment | bearish | 5 | gold | GLD | 1099 | -0.000418 | -0.000447 | - | - |
| trend_alignment | bearish | 5 | equity | (class signs) | 3 |  |  | +++ | +++ |
| trend_alignment | bearish | 5 | gold | (class signs) | 1 |  |  | - | - |
| trend_alignment | bearish | 5 | treasury | (class signs) | 1 |  |  | - | - |
| trend_alignment | bearish | 20 | equity | SPY | 724 | +0.008166 | +0.005908 | + | + |
| trend_alignment | bearish | 20 | equity | QQQ | 722 | +0.012303 | +0.010201 | + | + |
| trend_alignment | bearish | 20 | equity | IWM | 850 | +0.008756 | +0.007493 | + | + |
| trend_alignment | bearish | 20 | treasury | TLT | 1243 | -0.002737 | -0.001939 | - | - |
| trend_alignment | bearish | 20 | gold | GLD | 1099 | -0.001534 | -0.001155 | - | - |
| trend_alignment | bearish | 20 | equity | (class signs) | 3 |  |  | +++ | +++ |
| trend_alignment | bearish | 20 | gold | (class signs) | 1 |  |  | - | - |
| trend_alignment | bearish | 20 | treasury | (class signs) | 1 |  |  | - | - |
| trend_alignment | neutral | 1 | equity | SPY | 83 | +0.001271 | +0.000656 | + | + |
| trend_alignment | neutral | 1 | equity | QQQ | 62 | -0.002154 | -0.001451 | - | - |
| trend_alignment | neutral | 1 | equity | IWM | 86 | -0.001475 | -0.001813 | - | - |
| trend_alignment | neutral | 1 | treasury | TLT | 112 | +0.001065 | +0.000995 | + | + |
| trend_alignment | neutral | 1 | gold | GLD | 92 | -0.000109 | -0.000136 | - | - |
| trend_alignment | neutral | 1 | equity | (class signs) | 3 |  |  | +-- | +-- |
| trend_alignment | neutral | 1 | gold | (class signs) | 1 |  |  | - | - |
| trend_alignment | neutral | 1 | treasury | (class signs) | 1 |  |  | + | + |
| trend_alignment | neutral | 5 | equity | SPY | 83 | -0.002683 | +0.000597 | - | + |
| trend_alignment | neutral | 5 | equity | QQQ | 62 | -0.001404 | -0.002918 | - | - |
| trend_alignment | neutral | 5 | equity | IWM | 86 | +0.000780 | +0.003855 | + | + |
| trend_alignment | neutral | 5 | treasury | TLT | 112 | +0.001335 | +0.000111 | + | + |
| trend_alignment | neutral | 5 | gold | GLD | 92 | -0.003500 | -0.003979 | - | - |
| trend_alignment | neutral | 5 | equity | (class signs) | 3 |  |  | --+ | +-+ |
| trend_alignment | neutral | 5 | gold | (class signs) | 1 |  |  | - | - |
| trend_alignment | neutral | 5 | treasury | (class signs) | 1 |  |  | + | + |
| trend_alignment | neutral | 20 | equity | SPY | 83 | -0.006859 | -0.006772 | - | - |
| trend_alignment | neutral | 20 | equity | QQQ | 62 | -0.008403 | -0.005035 | - | - |
| trend_alignment | neutral | 20 | equity | IWM | 86 | -0.004818 | -0.003967 | - | - |
| trend_alignment | neutral | 20 | treasury | TLT | 112 | +0.001855 | +0.004829 | + | + |
| trend_alignment | neutral | 20 | gold | GLD | 92 | +0.000844 | -0.001333 | + | - |
| trend_alignment | neutral | 20 | equity | (class signs) | 3 |  |  | --- | --- |
| trend_alignment | neutral | 20 | gold | (class signs) | 1 |  |  | + | - |
| trend_alignment | neutral | 20 | treasury | (class signs) | 1 |  |  | + | + |
| momentum_in_trend_context | bullish | 1 | equity | SPY | 1189 | -0.000029 | -0.000050 | - | - |
| momentum_in_trend_context | bullish | 1 | equity | QQQ | 1187 | -0.000215 | -0.000302 | - | - |
| momentum_in_trend_context | bullish | 1 | equity | IWM | 874 | -0.000452 | -0.000277 | - | - |
| momentum_in_trend_context | bullish | 1 | treasury | TLT | 599 | +0.000037 | +0.000072 | + | + |
| momentum_in_trend_context | bullish | 1 | gold | GLD | 787 | +0.000013 | +0.000040 | + | + |
| momentum_in_trend_context | bullish | 1 | equity | (class signs) | 3 |  |  | --- | --- |
| momentum_in_trend_context | bullish | 1 | gold | (class signs) | 1 |  |  | + | + |
| momentum_in_trend_context | bullish | 1 | treasury | (class signs) | 1 |  |  | + | + |
| momentum_in_trend_context | bullish | 5 | equity | SPY | 1189 | -0.000458 | -0.000529 | - | - |
| momentum_in_trend_context | bullish | 5 | equity | QQQ | 1187 | -0.001205 | -0.001482 | - | - |
| momentum_in_trend_context | bullish | 5 | equity | IWM | 874 | -0.001849 | -0.002393 | - | - |
| momentum_in_trend_context | bullish | 5 | treasury | TLT | 599 | +0.000635 | +0.000720 | + | + |
| momentum_in_trend_context | bullish | 5 | gold | GLD | 787 | +0.000465 | +0.001253 | + | + |
| momentum_in_trend_context | bullish | 5 | equity | (class signs) | 3 |  |  | --- | --- |
| momentum_in_trend_context | bullish | 5 | gold | (class signs) | 1 |  |  | + | + |
| momentum_in_trend_context | bullish | 5 | treasury | (class signs) | 1 |  |  | + | + |
| momentum_in_trend_context | bullish | 20 | equity | SPY | 1189 | -0.004320 | -0.003443 | - | - |
| momentum_in_trend_context | bullish | 20 | equity | QQQ | 1187 | -0.005542 | -0.004167 | - | - |
| momentum_in_trend_context | bullish | 20 | equity | IWM | 874 | -0.008744 | -0.009773 | - | - |
| momentum_in_trend_context | bullish | 20 | treasury | TLT | 599 | +0.001745 | -0.003157 | + | - |
| momentum_in_trend_context | bullish | 20 | gold | GLD | 787 | +0.000107 | +0.000588 | + | + |
| momentum_in_trend_context | bullish | 20 | equity | (class signs) | 3 |  |  | --- | --- |
| momentum_in_trend_context | bullish | 20 | gold | (class signs) | 1 |  |  | + | + |
| momentum_in_trend_context | bullish | 20 | treasury | (class signs) | 1 |  |  | + | - |
| momentum_in_trend_context | bearish | 1 | equity | SPY | 279 | +0.000945 | +0.000867 | + | + |
| momentum_in_trend_context | bearish | 1 | equity | QQQ | 288 | +0.000647 | +0.000937 | + | + |
| momentum_in_trend_context | bearish | 1 | equity | IWM | 382 | +0.000330 | +0.000347 | + | + |
| momentum_in_trend_context | bearish | 1 | treasury | TLT | 696 | -0.000003 | +0.000069 | - | + |
| momentum_in_trend_context | bearish | 1 | gold | GLD | 496 | -0.000063 | +0.000026 | - | + |
| momentum_in_trend_context | bearish | 1 | equity | (class signs) | 3 |  |  | +++ | +++ |
| momentum_in_trend_context | bearish | 1 | gold | (class signs) | 1 |  |  | - | + |
| momentum_in_trend_context | bearish | 1 | treasury | (class signs) | 1 |  |  | - | + |
| momentum_in_trend_context | bearish | 5 | equity | SPY | 279 | +0.003748 | +0.005878 | + | + |
| momentum_in_trend_context | bearish | 5 | equity | QQQ | 288 | +0.005905 | +0.007323 | + | + |
| momentum_in_trend_context | bearish | 5 | equity | IWM | 382 | -0.000091 | +0.003815 | - | + |
| momentum_in_trend_context | bearish | 5 | treasury | TLT | 696 | -0.001401 | -0.001151 | - | - |
| momentum_in_trend_context | bearish | 5 | gold | GLD | 496 | -0.000367 | +0.000703 | - | + |
| momentum_in_trend_context | bearish | 5 | equity | (class signs) | 3 |  |  | ++- | +++ |
| momentum_in_trend_context | bearish | 5 | gold | (class signs) | 1 |  |  | - | + |
| momentum_in_trend_context | bearish | 5 | treasury | (class signs) | 1 |  |  | - | - |
| momentum_in_trend_context | bearish | 20 | equity | SPY | 279 | +0.015683 | +0.010390 | + | + |
| momentum_in_trend_context | bearish | 20 | equity | QQQ | 288 | +0.013923 | +0.009032 | + | + |
| momentum_in_trend_context | bearish | 20 | equity | IWM | 382 | +0.004706 | +0.001676 | + | + |
| momentum_in_trend_context | bearish | 20 | treasury | TLT | 696 | -0.006464 | -0.004587 | - | - |
| momentum_in_trend_context | bearish | 20 | gold | GLD | 496 | -0.000443 | +0.001133 | - | + |
| momentum_in_trend_context | bearish | 20 | equity | (class signs) | 3 |  |  | +++ | +++ |
| momentum_in_trend_context | bearish | 20 | gold | (class signs) | 1 |  |  | - | + |
| momentum_in_trend_context | bearish | 20 | treasury | (class signs) | 1 |  |  | - | - |
| momentum_in_trend_context | neutral | 1 | equity | SPY | 1048 | -0.000219 | -0.000004 | - | - |
| momentum_in_trend_context | neutral | 1 | equity | QQQ | 1041 | +0.000066 | +0.000559 | + | + |
| momentum_in_trend_context | neutral | 1 | equity | IWM | 1260 | +0.000213 | +0.000140 | + | + |
| momentum_in_trend_context | neutral | 1 | treasury | TLT | 1221 | -0.000016 | -0.000068 | - | - |
| momentum_in_trend_context | neutral | 1 | gold | GLD | 1233 | +0.000017 | -0.000040 | + | - |
| momentum_in_trend_context | neutral | 1 | equity | (class signs) | 3 |  |  | -++ | -++ |
| momentum_in_trend_context | neutral | 1 | gold | (class signs) | 1 |  |  | + | - |
| momentum_in_trend_context | neutral | 1 | treasury | (class signs) | 1 |  |  | - | - |
| momentum_in_trend_context | neutral | 5 | equity | SPY | 1048 | -0.000479 | +0.000528 | - | + |
| momentum_in_trend_context | neutral | 5 | equity | QQQ | 1041 | -0.000260 | +0.001236 | - | + |
| momentum_in_trend_context | neutral | 5 | equity | IWM | 1260 | +0.001310 | +0.001197 | + | + |
| momentum_in_trend_context | neutral | 5 | treasury | TLT | 1221 | +0.000487 | +0.000176 | + | + |
| momentum_in_trend_context | neutral | 5 | gold | GLD | 1233 | -0.000149 | -0.000922 | - | - |
| momentum_in_trend_context | neutral | 5 | equity | (class signs) | 3 |  |  | --+ | +++ |
| momentum_in_trend_context | neutral | 5 | gold | (class signs) | 1 |  |  | - | - |
| momentum_in_trend_context | neutral | 5 | treasury | (class signs) | 1 |  |  | + | + |
| momentum_in_trend_context | neutral | 20 | equity | SPY | 1048 | +0.000726 | +0.002538 | + | + |
| momentum_in_trend_context | neutral | 20 | equity | QQQ | 1041 | +0.002468 | +0.003175 | + | + |
| momentum_in_trend_context | neutral | 20 | equity | IWM | 1260 | +0.004639 | +0.007382 | + | + |
| momentum_in_trend_context | neutral | 20 | treasury | TLT | 1221 | +0.002828 | +0.004085 | + | + |
| momentum_in_trend_context | neutral | 20 | gold | GLD | 1233 | +0.000110 | -0.001374 | + | - |
| momentum_in_trend_context | neutral | 20 | equity | (class signs) | 3 |  |  | +++ | +++ |
| momentum_in_trend_context | neutral | 20 | gold | (class signs) | 1 |  |  | + | - |
| momentum_in_trend_context | neutral | 20 | treasury | (class signs) | 1 |  |  | + | + |
| trend_crossover | bullish | 1 | equity | SPY | 25 | +0.000698 | +0.000749 | + | + |
| trend_crossover | bullish | 1 | equity | QQQ | 25 | +0.000977 | +0.000306 | + | + |
| trend_crossover | bullish | 1 | equity | IWM | 29 | +0.000931 | +0.000953 | + | + |
| trend_crossover | bullish | 1 | treasury | TLT | 28 | +0.000382 | -0.000577 | + | - |
| trend_crossover | bullish | 1 | gold | GLD | 27 | -0.000157 | +0.000240 | - | + |
| trend_crossover | bullish | 1 | equity | (class signs) | 3 |  |  | +++ | +++ |
| trend_crossover | bullish | 1 | gold | (class signs) | 1 |  |  | - | + |
| trend_crossover | bullish | 1 | treasury | (class signs) | 1 |  |  | + | - |
| trend_crossover | bullish | 5 | equity | SPY | 25 | -0.001446 | -0.001188 | - | - |
| trend_crossover | bullish | 5 | equity | QQQ | 25 | +0.000120 | +0.000318 | + | + |
| trend_crossover | bullish | 5 | equity | IWM | 29 | +0.004312 | +0.007967 | + | + |
| trend_crossover | bullish | 5 | treasury | TLT | 28 | +0.004800 | +0.004422 | + | + |
| trend_crossover | bullish | 5 | gold | GLD | 27 | -0.004334 | -0.005884 | - | - |
| trend_crossover | bullish | 5 | equity | (class signs) | 3 |  |  | -++ | -++ |
| trend_crossover | bullish | 5 | gold | (class signs) | 1 |  |  | - | - |
| trend_crossover | bullish | 5 | treasury | (class signs) | 1 |  |  | + | + |
| trend_crossover | bullish | 20 | equity | SPY | 25 | -0.002908 | -0.004124 | - | - |
| trend_crossover | bullish | 20 | equity | QQQ | 25 | -0.004050 | +0.004101 | - | + |
| trend_crossover | bullish | 20 | equity | IWM | 29 | +0.006643 | -0.012128 | + | - |
| trend_crossover | bullish | 20 | treasury | TLT | 28 | +0.001566 | +0.002461 | + | + |
| trend_crossover | bullish | 20 | gold | GLD | 27 | +0.003743 | +0.009629 | + | + |
| trend_crossover | bullish | 20 | equity | (class signs) | 3 |  |  | --+ | -+- |
| trend_crossover | bullish | 20 | gold | (class signs) | 1 |  |  | + | + |
| trend_crossover | bullish | 20 | treasury | (class signs) | 1 |  |  | + | + |
| trend_crossover | bearish | 1 | equity | SPY | 25 | +0.002796 | +0.001304 | + | + |
| trend_crossover | bearish | 1 | equity | QQQ | 25 | -0.003517 | -0.003127 | - | - |
| trend_crossover | bearish | 1 | equity | IWM | 30 | +0.000441 | -0.000071 | + | - |
| trend_crossover | bearish | 1 | treasury | TLT | 29 | +0.000977 | +0.001951 | + | + |
| trend_crossover | bearish | 1 | gold | GLD | 28 | +0.000566 | +0.000084 | + | + |
| trend_crossover | bearish | 1 | equity | (class signs) | 3 |  |  | +-+ | +-- |
| trend_crossover | bearish | 1 | gold | (class signs) | 1 |  |  | + | + |
| trend_crossover | bearish | 1 | treasury | (class signs) | 1 |  |  | + | + |
| trend_crossover | bearish | 5 | equity | SPY | 25 | -0.005962 | +0.002602 | - | + |
| trend_crossover | bearish | 5 | equity | QQQ | 25 | -0.006268 | -0.004086 | - | - |
| trend_crossover | bearish | 5 | equity | IWM | 30 | -0.004165 | +0.002549 | - | + |
| trend_crossover | bearish | 5 | treasury | TLT | 29 | -0.001919 | +0.001891 | - | + |
| trend_crossover | bearish | 5 | gold | GLD | 28 | -0.001177 | -0.001308 | - | - |
| trend_crossover | bearish | 5 | equity | (class signs) | 3 |  |  | --- | +-+ |
| trend_crossover | bearish | 5 | gold | (class signs) | 1 |  |  | - | - |
| trend_crossover | bearish | 5 | treasury | (class signs) | 1 |  |  | - | + |
| trend_crossover | bearish | 20 | equity | SPY | 25 | -0.014454 | -0.019317 | - | - |
| trend_crossover | bearish | 20 | equity | QQQ | 25 | +0.001264 | +0.008976 | + | + |
| trend_crossover | bearish | 20 | equity | IWM | 30 | -0.001517 | +0.015719 | - | + |
| trend_crossover | bearish | 20 | treasury | TLT | 29 | +0.003699 | +0.006625 | + | + |
| trend_crossover | bearish | 20 | gold | GLD | 28 | +0.004501 | -0.003287 | + | - |
| trend_crossover | bearish | 20 | equity | (class signs) | 3 |  |  | -+- | -++ |
| trend_crossover | bearish | 20 | gold | (class signs) | 1 |  |  | + | - |
| trend_crossover | bearish | 20 | treasury | (class signs) | 1 |  |  | + | + |
| trend_crossover | neutral | 1 | equity | SPY | 2466 | -0.000035 | -0.000010 | - | - |
| trend_crossover | neutral | 1 | equity | QQQ | 2466 | +0.000026 | +0.000023 | + | + |
| trend_crossover | neutral | 1 | equity | IWM | 2457 | -0.000016 | -0.000041 | - | - |
| trend_crossover | neutral | 1 | treasury | TLT | 2459 | -0.000016 | -0.000001 | - | - |
| trend_crossover | neutral | 1 | gold | GLD | 2461 | -0.000005 | -0.000000 | - | - |
| trend_crossover | neutral | 1 | equity | (class signs) | 3 |  |  | -+- | -+- |
| trend_crossover | neutral | 1 | gold | (class signs) | 1 |  |  | - | - |
| trend_crossover | neutral | 1 | treasury | (class signs) | 1 |  |  | - | - |
| trend_crossover | neutral | 5 | equity | SPY | 2466 | +0.000075 | -0.000005 | + | - |
| trend_crossover | neutral | 5 | equity | QQQ | 2466 | +0.000062 | +0.000026 | + | + |
| trend_crossover | neutral | 5 | equity | IWM | 2457 | -0.000000 | -0.000216 | - | - |
| trend_crossover | neutral | 5 | treasury | TLT | 2459 | -0.000032 | -0.000107 | - | - |
| trend_crossover | neutral | 5 | gold | GLD | 2461 | +0.000061 | +0.000211 | + | + |
| trend_crossover | neutral | 5 | equity | (class signs) | 3 |  |  | ++- | -+- |
| trend_crossover | neutral | 5 | gold | (class signs) | 1 |  |  | + | + |
| trend_crossover | neutral | 5 | treasury | (class signs) | 1 |  |  | - | - |
| trend_crossover | neutral | 20 | equity | SPY | 2466 | +0.000176 | +0.000112 | + | + |
| trend_crossover | neutral | 20 | equity | QQQ | 2466 | +0.000028 | -0.000078 | + | - |
| trend_crossover | neutral | 20 | equity | IWM | 2457 | -0.000060 | -0.000097 | - | - |
| trend_crossover | neutral | 20 | treasury | TLT | 2459 | -0.000061 | -0.000280 | - | - |
| trend_crossover | neutral | 20 | gold | GLD | 2461 | -0.000092 | -0.000007 | - | - |
| trend_crossover | neutral | 20 | equity | (class signs) | 3 |  |  | ++- | +-- |
| trend_crossover | neutral | 20 | gold | (class signs) | 1 |  |  | - | - |
| trend_crossover | neutral | 20 | treasury | (class signs) | 1 |  |  | - | - |

## D5 — Crossover events

| symbol | timestamp | state | bars since previous cross | h1 | h5 | h20 |
|---|---|---|---|---|---|---|
| SPY | 2015-01-08T05:00:00+00:00 | bearish |  | -0.010417 | -0.035756 | -0.004118 |
| SPY | 2015-02-17T05:00:00+00:00 | bullish | 26 | +0.002242 | +0.010255 | -0.008108 |
| SPY | 2015-04-02T04:00:00+00:00 | bearish | 32 | +0.011978 | +0.022739 | +0.026051 |
| SPY | 2015-04-09T04:00:00+00:00 | bullish | 4 | +0.004015 | +0.005593 | -0.001577 |
| SPY | 2015-04-14T04:00:00+00:00 | bearish | 3 | +0.001809 | -0.002142 | -0.000333 |
| SPY | 2015-04-28T04:00:00+00:00 | bullish | 10 | +0.000951 | -0.006988 | +0.011076 |
| SPY | 2015-06-24T04:00:00+00:00 | bearish | 40 | -0.005874 | -0.017054 | -0.004358 |
| SPY | 2015-08-05T04:00:00+00:00 | bullish | 29 | -0.009225 | -0.006515 | -0.070759 |
| SPY | 2015-08-18T04:00:00+00:00 | bearish | 9 | -0.003683 | -0.104357 | -0.042613 |
| SPY | 2015-10-22T04:00:00+00:00 | bullish | 46 | +0.001254 | +0.007624 | +0.006273 |
| SPY | 2015-12-22T05:00:00+00:00 | bearish | 42 | +0.006498 | +0.006058 | -0.069227 |
| SPY | 2016-03-09T05:00:00+00:00 | bullish | 52 | -0.002100 | +0.016903 | +0.019954 |
| SPY | 2016-05-25T04:00:00+00:00 | bearish | 54 | -0.000477 | +0.007019 | +0.006541 |
| SPY | 2016-05-27T04:00:00+00:00 | bullish | 2 | -0.003419 | +0.003752 | -0.052052 |
| SPY | 2016-09-19T04:00:00+00:00 | bearish | 78 | -0.004617 | -0.000793 | -0.009468 |
| SPY | 2016-11-22T05:00:00+00:00 | bullish | 46 | +0.003273 | +0.001818 | +0.026321 |
| SPY | 2017-04-13T04:00:00+00:00 | bearish | 97 | +0.006263 | +0.006349 | +0.025181 |
| SPY | 2017-05-05T04:00:00+00:00 | bullish | 15 | -0.000375 | -0.003212 | +0.017685 |
| SPY | 2017-09-07T04:00:00+00:00 | bearish | 86 | +0.000162 | +0.014399 | +0.032936 |
| SPY | 2017-09-08T04:00:00+00:00 | bullish | 1 | +0.004717 | +0.004636 | +0.025520 |
| SPY | 2018-02-23T05:00:00+00:00 | bearish | 115 | +0.007139 | -0.024825 | -0.064799 |
| SPY | 2018-05-17T04:00:00+00:00 | bullish | 58 | -0.001068 | +0.004344 | +0.020286 |
| SPY | 2018-10-16T04:00:00+00:00 | bearish | 105 | +0.000036 | -0.024355 | -0.029882 |
| SPY | 2019-02-01T05:00:00+00:00 | bullish | 73 | +0.006849 | +0.001333 | +0.034393 |
| SPY | 2019-05-29T04:00:00+00:00 | bearish | 80 | -0.000287 | +0.013794 | +0.040701 |
| SPY | 2019-06-27T04:00:00+00:00 | bullish | 21 | +0.001436 | +0.020097 | +0.032231 |
| SPY | 2019-08-15T04:00:00+00:00 | bearish | 34 | +0.008273 | +0.020525 | +0.050998 |
| SPY | 2019-09-18T04:00:00+00:00 | bullish | 23 | -0.001492 | -0.012967 | -0.010380 |
| SPY | 2020-03-03T05:00:00+00:00 | bearish | 114 | +0.022017 | -0.057820 | -0.158010 |
| SPY | 2020-04-30T04:00:00+00:00 | bullish | 41 | -0.008832 | +0.008307 | +0.066629 |
| SPY | 2020-09-30T04:00:00+00:00 | bearish | 106 | -0.001925 | +0.009091 | -0.032663 |
| SPY | 2020-10-21T04:00:00+00:00 | bullish | 15 | +0.004811 | -0.047527 | +0.038838 |
| SPY | 2021-09-30T04:00:00+00:00 | bearish | 237 | +0.007564 | +0.017820 | +0.063437 |
| SPY | 2021-10-29T04:00:00+00:00 | bullish | 21 | -0.000565 | +0.017880 | +0.009342 |
| SPY | 2022-01-25T05:00:00+00:00 | bearish | 59 | -0.016655 | +0.027750 | -0.042589 |
| SPY | 2022-04-04T04:00:00+00:00 | bullish | 48 | -0.009204 | -0.033610 | -0.085321 |
| SPY | 2022-05-02T04:00:00+00:00 | bearish | 19 | +0.003301 | -0.040577 | -0.005012 |
| SPY | 2022-08-02T04:00:00+00:00 | bullish | 63 | +0.010115 | +0.002559 | -0.029466 |
| SPY | 2022-09-16T04:00:00+00:00 | bearish | 32 | +0.016455 | -0.037435 | -0.064433 |
| SPY | 2022-11-11T05:00:00+00:00 | bullish | 40 | -0.003882 | -0.001588 | +0.005773 |
| SPY | 2023-01-03T05:00:00+00:00 | bearish | 34 | +0.001514 | +0.019312 | +0.072081 |
| SPY | 2023-01-30T05:00:00+00:00 | bullish | 18 | +0.013337 | +0.021689 | -0.012141 |
| SPY | 2023-03-14T04:00:00+00:00 | bearish | 30 | +0.008785 | +0.033740 | +0.057426 |
| SPY | 2023-04-14T04:00:00+00:00 | bullish | 22 | +0.003807 | -0.000412 | -0.001892 |
| SPY | 2023-08-28T04:00:00+00:00 | bearish | 93 | +0.014707 | +0.014888 | -0.037885 |
| SPY | 2023-11-20T05:00:00+00:00 | bullish | 59 | +0.000199 | +0.003862 | +0.047796 |
| SPY | 2024-04-25T04:00:00+00:00 | bearish | 107 | +0.003772 | -0.002607 | +0.038728 |
| SPY | 2024-05-20T04:00:00+00:00 | bullish | 17 | +0.003930 | +0.001001 | +0.036295 |
| SPY | 2024-08-09T04:00:00+00:00 | bearish | 56 | -0.001760 | +0.037626 | +0.022837 |
| SPY | 2024-09-03T04:00:00+00:00 | bullish | 16 | +0.001363 | -0.002563 | +0.033479 |
| QQQ | 2015-01-08T05:00:00+00:00 | bearish |  | -0.009651 | -0.038313 | -0.004729 |
| QQQ | 2015-02-17T05:00:00+00:00 | bullish | 26 | +0.002620 | +0.016093 | -0.000094 |
| QQQ | 2015-04-17T04:00:00+00:00 | bearish | 42 | +0.009949 | +0.037545 | +0.028534 |
| QQQ | 2015-04-28T04:00:00+00:00 | bullish | 7 | -0.000731 | -0.018094 | +0.013982 |
| QQQ | 2015-06-30T04:00:00+00:00 | bearish | 44 | -0.001942 | -0.018866 | +0.031629 |
| QQQ | 2015-07-28T04:00:00+00:00 | bullish | 19 | +0.001616 | +0.000180 | -0.119242 |
| QQQ | 2015-08-25T04:00:00+00:00 | bearish | 20 | +0.020503 | +0.000891 | +0.031894 |
| QQQ | 2015-10-22T04:00:00+00:00 | bullish | 41 | +0.001065 | +0.010474 | +0.009320 |
| QQQ | 2015-12-30T05:00:00+00:00 | bearish | 47 | -0.008948 | -0.070878 | -0.077434 |
| QQQ | 2016-03-11T05:00:00+00:00 | bullish | 49 | +0.005467 | +0.012065 | +0.023659 |
| QQQ | 2016-05-12T04:00:00+00:00 | bearish | 43 | -0.002836 | -0.004631 | +0.029679 |
| QQQ | 2016-06-10T04:00:00+00:00 | bullish | 20 | -0.002677 | -0.016894 | +0.024095 |
| QQQ | 2016-07-06T04:00:00+00:00 | bearish | 17 | +0.002030 | +0.026015 | +0.064022 |
| QQQ | 2016-07-14T04:00:00+00:00 | bullish | 6 | -0.003920 | +0.008375 | +0.043478 |
| QQQ | 2016-11-04T04:00:00+00:00 | bearish | 80 | +0.007447 | +0.002684 | +0.009611 |
| QQQ | 2016-12-09T05:00:00+00:00 | bullish | 24 | -0.000084 | +0.005295 | +0.030512 |
| QQQ | 2017-07-07T04:00:00+00:00 | bearish | 143 | +0.005876 | +0.030976 | +0.042075 |
| QQQ | 2017-07-25T04:00:00+00:00 | bullish | 12 | +0.000760 | -0.008290 | -0.010776 |
| QQQ | 2018-04-05T04:00:00+00:00 | bearish | 175 | -0.014162 | +0.020959 | +0.018379 |
| QQQ | 2018-05-15T04:00:00+00:00 | bullish | 28 | +0.005295 | +0.000535 | +0.045987 |
| QQQ | 2018-10-12T04:00:00+00:00 | bearish | 105 | -0.008635 | -0.003972 | -0.012607 |
| QQQ | 2019-01-30T05:00:00+00:00 | bullish | 73 | +0.008758 | +0.022915 | +0.038932 |
| QQQ | 2019-05-28T04:00:00+00:00 | bearish | 81 | -0.002041 | -0.008390 | +0.048415 |
| QQQ | 2019-07-01T04:00:00+00:00 | bullish | 24 | +0.004281 | +0.007717 | +0.024207 |
| QQQ | 2019-08-19T04:00:00+00:00 | bearish | 34 | -0.005267 | -0.016706 | +0.024686 |
| QQQ | 2019-09-20T04:00:00+00:00 | bullish | 23 | +0.000735 | -0.017493 | +0.006987 |
| QQQ | 2020-03-10T04:00:00+00:00 | bearish | 117 | -0.020717 | -0.086331 | -0.014798 |
| QQQ | 2020-04-27T04:00:00+00:00 | bullish | 33 | -0.026781 | -0.009663 | +0.053930 |
| QQQ | 2020-10-01T04:00:00+00:00 | bearish | 110 | -0.006195 | +0.019528 | +0.001341 |
| QQQ | 2020-10-16T04:00:00+00:00 | bullish | 11 | -0.023030 | -0.019794 | +0.001515 |
| QQQ | 2021-03-11T05:00:00+00:00 | bearish | 99 | +0.005098 | -0.005799 | +0.074078 |
| QQQ | 2021-04-13T04:00:00+00:00 | bullish | 22 | -0.012733 | -0.013026 | -0.045592 |
| QQQ | 2021-05-26T04:00:00+00:00 | bearish | 31 | -0.002368 | -0.010999 | +0.048611 |
| QQQ | 2021-06-16T04:00:00+00:00 | bullish | 14 | +0.015795 | +0.022855 | +0.060446 |
| QQQ | 2021-10-05T04:00:00+00:00 | bearish | 77 | +0.015787 | +0.008642 | +0.098763 |
| QQQ | 2021-11-02T04:00:00+00:00 | bullish | 20 | +0.009318 | +0.014812 | -0.006238 |
| QQQ | 2022-01-07T05:00:00+00:00 | bearish | 46 | +0.014113 | +0.013847 | -0.052532 |
| QQQ | 2022-04-05T04:00:00+00:00 | bullish | 60 | -0.006720 | -0.045550 | -0.073246 |
| QQQ | 2022-04-28T04:00:00+00:00 | bearish | 16 | -0.032283 | -0.033055 | -0.075286 |
| QQQ | 2022-07-28T04:00:00+00:00 | bullish | 62 | +0.013070 | +0.041780 | +0.029513 |
| QQQ | 2022-09-14T04:00:00+00:00 | bearish | 33 | -0.010100 | -0.035740 | -0.106811 |
| QQQ | 2022-11-21T05:00:00+00:00 | bullish | 48 | +0.011711 | -0.007324 | -0.046349 |
| QQQ | 2022-12-29T05:00:00+00:00 | bearish | 26 | +0.010090 | +0.019649 | +0.101092 |
| QQQ | 2023-01-31T05:00:00+00:00 | bullish | 21 | +0.022112 | +0.052546 | -0.010903 |
| QQQ | 2023-08-23T04:00:00+00:00 | bearish | 141 | -0.030646 | +0.011325 | -0.039663 |
| QQQ | 2023-11-17T05:00:00+00:00 | bullish | 61 | +0.012149 | +0.008082 | +0.054475 |
| QQQ | 2024-04-22T04:00:00+00:00 | bearish | 105 | +0.010219 | +0.028472 | +0.081137 |
| QQQ | 2024-05-21T04:00:00+00:00 | bullish | 21 | -0.000767 | +0.000833 | +0.055716 |
| QQQ | 2024-08-06T04:00:00+00:00 | bearish | 52 | -0.026249 | +0.036037 | +0.031624 |
| QQQ | 2024-09-16T04:00:00+00:00 | bullish | 28 | -0.005879 | +0.014172 | +0.044532 |
| IWM | 2015-01-30T05:00:00+00:00 | bearish |  | +0.005512 | +0.031777 | +0.063297 |
| IWM | 2015-02-06T05:00:00+00:00 | bullish | 5 | -0.004523 | +0.017839 | +0.019263 |
| IWM | 2015-05-13T04:00:00+00:00 | bearish | 66 | +0.005769 | +0.016493 | +0.026243 |
| IWM | 2015-06-09T04:00:00+00:00 | bullish | 18 | +0.008485 | +0.011927 | -0.023533 |
| IWM | 2015-07-22T04:00:00+00:00 | bearish | 30 | -0.011361 | -0.024402 | -0.044644 |
| IWM | 2015-10-28T04:00:00+00:00 | bullish | 69 | -0.007452 | +0.013277 | +0.020815 |
| IWM | 2015-12-18T05:00:00+00:00 | bearish | 36 | +0.001337 | +0.016047 | -0.115806 |
| IWM | 2016-03-10T05:00:00+00:00 | bullish | 55 | +0.013203 | +0.017230 | +0.021725 |
| IWM | 2016-10-20T04:00:00+00:00 | bearish | 156 | +0.006735 | -0.015799 | +0.083486 |
| IWM | 2016-11-21T05:00:00+00:00 | bullish | 22 | +0.005147 | +0.001060 | +0.044202 |
| IWM | 2017-02-09T05:00:00+00:00 | bearish | 54 | +0.001089 | +0.010233 | -0.013281 |
| IWM | 2017-02-14T05:00:00+00:00 | bullish | 3 | +0.010131 | +0.010059 | -0.003329 |
| IWM | 2017-03-27T04:00:00+00:00 | bearish | 28 | +0.011245 | +0.013032 | +0.044608 |
| IWM | 2017-05-02T04:00:00+00:00 | bullish | 25 | -0.001444 | -0.001011 | -0.015669 |
| IWM | 2017-08-15T04:00:00+00:00 | bearish | 73 | -0.001671 | -0.010024 | +0.031162 |
| IWM | 2017-09-21T04:00:00+00:00 | bullish | 26 | +0.004385 | +0.028955 | +0.039117 |
| IWM | 2018-02-16T05:00:00+00:00 | bearish | 102 | -0.003081 | +0.015995 | +0.024451 |
| IWM | 2018-03-16T04:00:00+00:00 | bullish | 19 | -0.005663 | -0.045301 | -0.011453 |
| IWM | 2018-04-13T04:00:00+00:00 | bearish | 19 | +0.003423 | +0.004585 | +0.032291 |
| IWM | 2018-05-01T04:00:00+00:00 | bullish | 12 | +0.005657 | +0.026336 | +0.066979 |
| IWM | 2018-08-17T04:00:00+00:00 | bearish | 76 | +0.000059 | +0.016468 | +0.004443 |
| IWM | 2018-08-21T04:00:00+00:00 | bullish | 2 | +0.003459 | +0.008265 | -0.005510 |
| IWM | 2018-10-05T04:00:00+00:00 | bearish | 32 | +0.000309 | -0.050504 | -0.048031 |
| IWM | 2019-01-30T05:00:00+00:00 | bullish | 78 | +0.009823 | +0.022492 | +0.062123 |
| IWM | 2019-05-28T04:00:00+00:00 | bearish | 81 | -0.003359 | +0.008869 | +0.015520 |
| IWM | 2019-07-08T04:00:00+00:00 | bullish | 28 | +0.005565 | +0.004853 | -0.042319 |
| IWM | 2019-08-13T04:00:00+00:00 | bearish | 26 | -0.012707 | +0.008111 | +0.061169 |
| IWM | 2019-09-23T04:00:00+00:00 | bullish | 28 | -0.017531 | -0.024557 | -0.007154 |
| IWM | 2019-10-17T04:00:00+00:00 | bearish | 18 | -0.002092 | +0.008174 | +0.033806 |
| IWM | 2019-10-30T04:00:00+00:00 | bullish | 9 | -0.004164 | +0.013645 | +0.043113 |
| IWM | 2020-02-24T05:00:00+00:00 | bearish | 78 | -0.038211 | -0.070699 | -0.385306 |
| IWM | 2020-05-06T04:00:00+00:00 | bullish | 51 | +0.000393 | -0.036659 | +0.135018 |
| IWM | 2020-09-24T04:00:00+00:00 | bearish | 98 | +0.020706 | +0.060931 | +0.130298 |
| IWM | 2020-10-19T04:00:00+00:00 | bullish | 17 | -0.004952 | -0.012441 | +0.099468 |
| IWM | 2021-04-13T04:00:00+00:00 | bearish | 120 | +0.006535 | -0.021093 | -0.013116 |
| IWM | 2021-04-28T04:00:00+00:00 | bullish | 11 | -0.012389 | -0.036604 | -0.032489 |
| IWM | 2021-05-13T04:00:00+00:00 | bearish | 11 | +0.014132 | +0.006699 | +0.063137 |
| IWM | 2021-06-09T04:00:00+00:00 | bullish | 18 | -0.010359 | -0.007812 | -0.043077 |
| IWM | 2021-07-21T04:00:00+00:00 | bearish | 29 | -0.013275 | -0.002935 | -0.031426 |
| IWM | 2021-09-08T04:00:00+00:00 | bullish | 34 | +0.001208 | -0.006755 | -0.016418 |
| IWM | 2021-10-06T04:00:00+00:00 | bearish | 20 | +0.007809 | +0.004695 | +0.077236 |
| IWM | 2021-10-18T04:00:00+00:00 | bullish | 8 | -0.000487 | +0.015886 | +0.055624 |
| IWM | 2021-12-09T05:00:00+00:00 | bearish | 37 | -0.010306 | -0.040594 | -0.027588 |
| IWM | 2022-03-28T04:00:00+00:00 | bullish | 74 | +0.017837 | -0.000433 | -0.097404 |
| IWM | 2022-04-26T04:00:00+00:00 | bearish | 20 | -0.003783 | +0.004369 | -0.064475 |
| IWM | 2022-08-01T04:00:00+00:00 | bullish | 66 | +0.002842 | +0.034054 | +0.004129 |
| IWM | 2022-09-19T04:00:00+00:00 | bearish | 34 | -0.003972 | -0.081669 | -0.037143 |
| IWM | 2022-11-09T05:00:00+00:00 | bullish | 37 | +0.019412 | +0.013198 | -0.005554 |
| IWM | 2022-12-23T05:00:00+00:00 | bearish | 31 | -0.006538 | -0.005506 | +0.075075 |
| IWM | 2023-01-26T05:00:00+00:00 | bullish | 21 | +0.008512 | +0.055006 | -0.002500 |
| IWM | 2023-03-15T04:00:00+00:00 | bearish | 33 | +0.026302 | +0.000991 | +0.039074 |
| IWM | 2023-06-02T04:00:00+00:00 | bullish | 55 | -0.009268 | +0.020799 | +0.035253 |
| IWM | 2023-08-28T04:00:00+00:00 | bearish | 59 | +0.014498 | +0.006953 | -0.060257 |
| IWM | 2023-11-27T05:00:00+00:00 | bullish | 63 | -0.002856 | +0.046710 | +0.143097 |
| IWM | 2024-04-19T04:00:00+00:00 | bearish | 99 | +0.005612 | +0.021369 | +0.071418 |
| IWM | 2024-05-20T04:00:00+00:00 | bullish | 21 | +0.002454 | -0.012847 | -0.034066 |
| IWM | 2024-06-27T04:00:00+00:00 | bearish | 26 | -0.004856 | -0.014764 | +0.099765 |
| IWM | 2024-07-17T04:00:00+00:00 | bullish | 13 | -0.015627 | -0.016079 | -0.066528 |
| IWM | 2024-12-31T05:00:00+00:00 | bearish | 116 | -0.008029 | -0.005473 | +0.015924 |
| TLT | 2015-03-02T05:00:00+00:00 | bearish |  | -0.003783 | -0.017732 | +0.027741 |
| TLT | 2015-04-08T04:00:00+00:00 | bullish | 26 | -0.011003 | -0.001987 | -0.078780 |
| TLT | 2015-05-04T04:00:00+00:00 | bearish | 18 | -0.001628 | -0.027104 | -0.027837 |
| TLT | 2015-07-29T04:00:00+00:00 | bullish | 60 | +0.003465 | +0.003630 | +0.005940 |
| TLT | 2015-09-21T04:00:00+00:00 | bearish | 37 | +0.002800 | +0.017951 | +0.017704 |
| TLT | 2015-10-15T04:00:00+00:00 | bullish | 18 | -0.002575 | +0.000081 | -0.042254 |
| TLT | 2015-11-11T05:00:00+00:00 | bearish | 19 | +0.002105 | +0.010695 | +0.026021 |
| TLT | 2015-12-21T05:00:00+00:00 | bullish | 27 | -0.002772 | -0.020302 | +0.025846 |
| TLT | 2016-03-29T04:00:00+00:00 | bearish | 66 | -0.002615 | +0.016612 | -0.021380 |
| TLT | 2016-04-11T04:00:00+00:00 | bullish | 9 | -0.001144 | +0.001755 | -0.001678 |
| TLT | 2016-05-12T04:00:00+00:00 | bearish | 23 | +0.006085 | -0.010876 | +0.025099 |
| TLT | 2016-05-23T04:00:00+00:00 | bullish | 7 | -0.000846 | +0.001462 | +0.027468 |
| TLT | 2016-08-31T04:00:00+00:00 | bearish | 70 | +0.008296 | -0.005988 | +0.000938 |
| TLT | 2017-01-23T05:00:00+00:00 | bullish | 98 | -0.003809 | -0.012420 | -0.005465 |
| TLT | 2017-03-08T05:00:00+00:00 | bearish | 31 | -0.004261 | +0.009886 | +0.034430 |
| TLT | 2017-04-06T04:00:00+00:00 | bullish | 21 | -0.009274 | +0.013378 | -0.004514 |
| TLT | 2017-07-25T04:00:00+00:00 | bearish | 75 | +0.004056 | +0.011114 | +0.025716 |
| TLT | 2017-08-22T04:00:00+00:00 | bullish | 20 | +0.002047 | +0.004802 | -0.008895 |
| TLT | 2017-10-05T04:00:00+00:00 | bearish | 31 | +0.002433 | +0.013464 | +0.016303 |
| TLT | 2017-11-22T05:00:00+00:00 | bullish | 34 | -0.001024 | -0.014260 | -0.018357 |
| TLT | 2018-01-10T05:00:00+00:00 | bearish | 32 | +0.006477 | +0.001619 | -0.039025 |
| TLT | 2018-04-04T04:00:00+00:00 | bullish | 57 | -0.002581 | +0.011740 | -0.015154 |
| TLT | 2018-05-04T04:00:00+00:00 | bearish | 22 | -0.001429 | +0.002185 | +0.003867 |
| TLT | 2018-06-14T04:00:00+00:00 | bullish | 28 | -0.003724 | -0.002400 | +0.015642 |
| TLT | 2018-08-06T04:00:00+00:00 | bearish | 36 | -0.003024 | +0.011594 | +0.008401 |
| TLT | 2018-09-05T04:00:00+00:00 | bullish | 21 | +0.003257 | -0.006847 | -0.041166 |
| TLT | 2018-09-17T04:00:00+00:00 | bearish | 8 | -0.006353 | -0.010672 | -0.030832 |
| TLT | 2018-12-06T05:00:00+00:00 | bullish | 56 | +0.005093 | +0.002207 | +0.033444 |
| TLT | 2019-03-12T04:00:00+00:00 | bearish | 64 | +0.001397 | -0.002055 | +0.019070 |
| TLT | 2019-03-18T04:00:00+00:00 | bullish | 4 | +0.002643 | +0.032786 | +0.015608 |
| TLT | 2019-03-19T04:00:00+00:00 | bearish | 1 | +0.007721 | +0.026532 | +0.003861 |
| TLT | 2019-03-21T04:00:00+00:00 | bullish | 2 | +0.005233 | +0.018920 | -0.010547 |
| TLT | 2019-10-03T04:00:00+00:00 | bearish | 136 | +0.004403 | -0.021672 | -0.028277 |
| TLT | 2019-12-16T05:00:00+00:00 | bullish | 51 | -0.004414 | -0.012734 | +0.010419 |
| TLT | 2019-12-26T05:00:00+00:00 | bearish | 7 | -0.000873 | +0.012223 | +0.049840 |
| TLT | 2020-01-27T05:00:00+00:00 | bullish | 20 | -0.005350 | +0.011186 | +0.049469 |
| TLT | 2020-05-28T04:00:00+00:00 | bearish | 85 | +0.005408 | -0.033680 | +0.004855 |
| TLT | 2020-07-10T04:00:00+00:00 | bullish | 30 | +0.008338 | +0.007734 | +0.026465 |
| TLT | 2020-08-28T04:00:00+00:00 | bearish | 35 | +0.003651 | +0.007054 | +0.018874 |
| TLT | 2021-04-29T04:00:00+00:00 | bullish | 167 | +0.000939 | +0.010180 | +0.001083 |
| TLT | 2021-05-28T04:00:00+00:00 | bearish | 21 | +0.002830 | +0.011972 | +0.040995 |
| TLT | 2021-06-10T04:00:00+00:00 | bullish | 8 | +0.000000 | +0.005130 | +0.029654 |
| TLT | 2021-09-28T04:00:00+00:00 | bearish | 76 | -0.003177 | -0.008425 | +0.002072 |
| TLT | 2021-11-17T05:00:00+00:00 | bullish | 36 | +0.005617 | +0.005685 | +0.021577 |
| TLT | 2022-01-05T05:00:00+00:00 | bearish | 33 | +0.004909 | +0.002945 | -0.010520 |
| TLT | 2022-07-25T04:00:00+00:00 | bullish | 137 | -0.011610 | +0.009928 | -0.052162 |
| TLT | 2022-08-30T04:00:00+00:00 | bearish | 26 | -0.007188 | -0.031059 | -0.074186 |
| TLT | 2022-12-02T05:00:00+00:00 | bullish | 66 | -0.002362 | +0.004630 | -0.041383 |
| TLT | 2023-02-23T05:00:00+00:00 | bearish | 55 | -0.004633 | -0.019322 | +0.048896 |
| TLT | 2023-03-30T04:00:00+00:00 | bullish | 25 | +0.009682 | +0.030185 | +0.010536 |
| TLT | 2023-05-10T04:00:00+00:00 | bearish | 28 | -0.001425 | -0.025831 | -0.030769 |
| TLT | 2023-11-24T05:00:00+00:00 | bullish | 137 | +0.011074 | +0.029790 | +0.090587 |
| TLT | 2024-02-01T05:00:00+00:00 | bearish | 46 | -0.002077 | -0.023164 | -0.018697 |
| TLT | 2024-03-26T04:00:00+00:00 | bullish | 37 | +0.007554 | -0.020960 | -0.059474 |
| TLT | 2024-04-02T04:00:00+00:00 | bearish | 4 | +0.008328 | +0.010629 | -0.033311 |
| TLT | 2024-05-31T04:00:00+00:00 | bullish | 42 | +0.010591 | +0.009488 | -0.008054 |
| TLT | 2024-10-10T04:00:00+00:00 | bearish | 91 | +0.002353 | +0.003423 | -0.023000 |
| GLD | 2015-03-02T05:00:00+00:00 | bearish |  | -0.004912 | -0.035074 | -0.019735 |
| GLD | 2015-04-17T04:00:00+00:00 | bullish | 33 | -0.000871 | -0.015415 | +0.023602 |
| GLD | 2015-06-10T04:00:00+00:00 | bearish | 37 | -0.000088 | +0.005121 | -0.016862 |
| GLD | 2015-09-04T04:00:00+00:00 | bullish | 61 | -0.000744 | -0.012825 | +0.010874 |
| GLD | 2015-11-12T05:00:00+00:00 | bearish | 48 | +0.000193 | +0.000193 | -0.004153 |
| GLD | 2016-01-14T05:00:00+00:00 | bullish | 42 | -0.008006 | +0.000763 | +0.128098 |
| GLD | 2016-04-18T04:00:00+00:00 | bearish | 64 | -0.002419 | -0.013681 | +0.016101 |
| GLD | 2016-04-29T04:00:00+00:00 | bullish | 9 | -0.004363 | -0.004847 | -0.065923 |
| GLD | 2016-06-06T04:00:00+00:00 | bearish | 25 | +0.002700 | +0.034937 | +0.092574 |
| GLD | 2016-06-24T04:00:00+00:00 | bullish | 14 | +0.001898 | +0.015581 | -0.007672 |
| GLD | 2016-09-01T04:00:00+00:00 | bearish | 48 | +0.002217 | +0.003642 | -0.005147 |
| GLD | 2017-01-24T05:00:00+00:00 | bullish | 98 | +0.001577 | +0.012353 | +0.033030 |
| GLD | 2017-05-18T04:00:00+00:00 | bearish | 80 | +0.000084 | +0.000754 | -0.000419 |
| GLD | 2017-06-08T04:00:00+00:00 | bullish | 14 | +0.000664 | -0.009464 | -0.043002 |
| GLD | 2017-07-05T04:00:00+00:00 | bearish | 18 | -0.000944 | -0.004718 | +0.032767 |
| GLD | 2017-08-09T04:00:00+00:00 | bullish | 25 | +0.001065 | -0.001720 | +0.049558 |
| GLD | 2017-10-10T04:00:00+00:00 | bearish | 43 | +0.001795 | -0.003590 | -0.011096 |
| GLD | 2017-12-04T05:00:00+00:00 | bullish | 38 | +0.001832 | -0.017402 | +0.039301 |
| GLD | 2017-12-07T05:00:00+00:00 | bearish | 3 | -0.000084 | +0.003713 | +0.057558 |
| GLD | 2018-01-08T05:00:00+00:00 | bullish | 20 | +0.001928 | +0.021528 | +0.007149 |
| GLD | 2018-03-12T04:00:00+00:00 | bearish | 43 | +0.000875 | -0.006366 | +0.011538 |
| GLD | 2018-04-10T04:00:00+00:00 | bullish | 20 | +0.000156 | -0.002654 | -0.027325 |
| GLD | 2018-05-08T04:00:00+00:00 | bearish | 20 | -0.000964 | -0.015830 | -0.012294 |
| GLD | 2018-10-12T04:00:00+00:00 | bullish | 110 | -0.001033 | -0.000947 | -0.014123 |
| GLD | 2019-03-21T04:00:00+00:00 | bearish | 108 | +0.000323 | -0.016380 | -0.028726 |
| GLD | 2019-06-04T04:00:00+00:00 | bullish | 51 | -0.005627 | -0.007925 | +0.057299 |
| GLD | 2019-10-07T04:00:00+00:00 | bearish | 87 | -0.000774 | -0.010139 | +0.000845 |
| GLD | 2019-12-30T05:00:00+00:00 | bullish | 58 | -0.002861 | +0.032517 | +0.035936 |
| GLD | 2020-03-31T04:00:00+00:00 | bearish | 63 | +0.008435 | +0.052901 | +0.091296 |
| GLD | 2020-04-14T04:00:00+00:00 | bullish | 9 | +0.000309 | -0.019716 | -0.010878 |
| GLD | 2020-09-24T04:00:00+00:00 | bearish | 114 | +0.003039 | +0.024597 | +0.025343 |
| GLD | 2021-01-05T05:00:00+00:00 | bullish | 70 | -0.008761 | -0.040608 | -0.053116 |
| GLD | 2021-02-03T05:00:00+00:00 | bearish | 20 | -0.000832 | +0.026264 | -0.054965 |
| GLD | 2021-04-26T04:00:00+00:00 | bullish | 56 | -0.002995 | +0.005332 | +0.056494 |
| GLD | 2021-06-30T04:00:00+00:00 | bearish | 46 | -0.002700 | +0.012001 | +0.027123 |
| GLD | 2021-09-10T04:00:00+00:00 | bullish | 50 | +0.001732 | -0.021977 | -0.019230 |
| GLD | 2021-09-21T04:00:00+00:00 | bearish | 7 | -0.002833 | -0.023148 | -0.002652 |
| GLD | 2021-11-03T04:00:00+00:00 | bullish | 31 | +0.000836 | +0.033670 | -0.013551 |
| GLD | 2021-12-15T05:00:00+00:00 | bearish | 29 | +0.006886 | +0.009461 | +0.018861 |
| GLD | 2022-01-18T05:00:00+00:00 | bullish | 22 | +0.009918 | +0.012853 | +0.015787 |
| GLD | 2022-04-28T04:00:00+00:00 | bearish | 70 | -0.006514 | -0.016510 | -0.029820 |
| GLD | 2022-08-24T04:00:00+00:00 | bullish | 81 | -0.001342 | -0.028664 | -0.050436 |
| GLD | 2022-09-06T04:00:00+00:00 | bearish | 8 | +0.011318 | +0.002466 | +0.016124 |
| GLD | 2022-11-15T05:00:00+00:00 | bullish | 50 | -0.001753 | -0.020192 | +0.016263 |
| GLD | 2023-02-28T05:00:00+00:00 | bearish | 70 | -0.001111 | -0.013630 | +0.073062 |
| GLD | 2023-03-24T04:00:00+00:00 | bullish | 18 | +0.004416 | +0.011427 | +0.020204 |
| GLD | 2023-05-31T04:00:00+00:00 | bearish | 46 | +0.005197 | -0.014551 | -0.031289 |
| GLD | 2023-07-31T04:00:00+00:00 | bullish | 41 | -0.002156 | -0.005917 | -0.015040 |
| GLD | 2023-08-16T04:00:00+00:00 | bearish | 12 | -0.006968 | +0.007704 | +0.003625 |
| GLD | 2023-10-30T04:00:00+00:00 | bullish | 52 | -0.005349 | -0.009347 | +0.022585 |
| GLD | 2024-01-31T05:00:00+00:00 | bearish | 63 | +0.003690 | -0.006378 | -0.002109 |
| GLD | 2024-03-06T05:00:00+00:00 | bullish | 24 | +0.002005 | +0.008269 | +0.060038 |
| GLD | 2024-06-17T04:00:00+00:00 | bearish | 71 | +0.005084 | +0.000840 | +0.059940 |
| GLD | 2024-07-15T04:00:00+00:00 | bullish | 18 | +0.012597 | -0.016190 | +0.013129 |
| GLD | 2024-11-26T05:00:00+00:00 | bearish | 95 | -0.005554 | -0.000735 | -0.007270 |

## Predeclared descriptive decision aids

These are reading aids for the review gate, computed for every symbol, state and horizon. They are not statistical tests, confidence criteria, robustness proofs or acceptance thresholds, and nothing is selected by them.

| aid | hypothesis | symbol | class | state | h | detail |
|---|---|---|---|---|---|---|
| segment_sign_agreement | trend_alignment | SPY | equity | bullish | 1 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=3; segments_with_same_median_sign=3; majority_threshold=4 |
| segment_sign_agreement | trend_alignment | SPY | equity | bullish | 5 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=4; majority_threshold=4 |
| segment_sign_agreement | trend_alignment | SPY | equity | bullish | 20 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=4; majority_threshold=4 |
| episode_concentration | trend_alignment | SPY | equity | bullish |  | observations=1709; episodes=26; share_largest_episode=+0.138678; share_three_largest=+0.269163; share_threshold=+0.250000 |
| segment_sign_agreement | trend_alignment | SPY | equity | bearish | 1 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=3; segments_with_same_median_sign=2; majority_threshold=4 |
| segment_sign_agreement | trend_alignment | SPY | equity | bearish | 5 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=4; majority_threshold=4 |
| segment_sign_agreement | trend_alignment | SPY | equity | bearish | 20 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=4; majority_threshold=4 |
| episode_concentration | trend_alignment | SPY | equity | bearish |  | observations=724; episodes=23; share_largest_episode=+0.099448; share_three_largest=+0.266575; share_threshold=+0.250000 |
| segment_sign_agreement | trend_alignment | QQQ | equity | bullish | 1 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=3; segments_with_same_median_sign=3; majority_threshold=4 |
| segment_sign_agreement | trend_alignment | QQQ | equity | bullish | 5 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=4; majority_threshold=4 |
| segment_sign_agreement | trend_alignment | QQQ | equity | bullish | 20 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=4; majority_threshold=4 |
| episode_concentration | trend_alignment | QQQ | equity | bullish |  | observations=1732; episodes=27; share_largest_episode=+0.087182; share_three_largest=+0.250000; share_threshold=+0.250000 |
| segment_sign_agreement | trend_alignment | QQQ | equity | bearish | 1 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=3; majority_threshold=4 |
| segment_sign_agreement | trend_alignment | QQQ | equity | bearish | 5 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=4; majority_threshold=4 |
| segment_sign_agreement | trend_alignment | QQQ | equity | bearish | 20 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=4; majority_threshold=4 |
| episode_concentration | trend_alignment | QQQ | equity | bearish |  | observations=722; episodes=25; share_largest_episode=+0.101108; share_three_largest=+0.268698; share_threshold=+0.250000 |
| segment_sign_agreement | trend_alignment | IWM | equity | bullish | 1 | full_window_mean_delta_sign=-; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=3; segments_with_same_median_sign=4; majority_threshold=4 |
| segment_sign_agreement | trend_alignment | IWM | equity | bullish | 5 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=3; segments_with_same_median_sign=4; majority_threshold=4 |
| segment_sign_agreement | trend_alignment | IWM | equity | bullish | 20 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=5; segments_with_same_median_sign=4; majority_threshold=4 |
| episode_concentration | trend_alignment | IWM | equity | bullish |  | observations=1580; episodes=32; share_largest_episode=+0.096835; share_three_largest=+0.237342; share_threshold=+0.250000 |
| segment_sign_agreement | trend_alignment | IWM | equity | bearish | 1 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=4; majority_threshold=4 |
| segment_sign_agreement | trend_alignment | IWM | equity | bearish | 5 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=3; segments_with_same_median_sign=3; majority_threshold=4 |
| segment_sign_agreement | trend_alignment | IWM | equity | bearish | 20 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=5; segments_with_same_median_sign=5; majority_threshold=4 |
| episode_concentration | trend_alignment | IWM | equity | bearish |  | observations=850; episodes=27; share_largest_episode=+0.091765; share_three_largest=+0.256471; share_threshold=+0.250000 |
| segment_sign_agreement | trend_alignment | TLT | treasury | bullish | 1 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=4; majority_threshold=4 |
| segment_sign_agreement | trend_alignment | TLT | treasury | bullish | 5 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=4; majority_threshold=4 |
| segment_sign_agreement | trend_alignment | TLT | treasury | bullish | 20 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=3; segments_with_same_median_sign=3; majority_threshold=4 |
| episode_concentration | trend_alignment | TLT | treasury | bullish |  | observations=1161; episodes=27; share_largest_episode=+0.116279; share_three_largest=+0.265289; share_threshold=+0.250000 |
| segment_sign_agreement | trend_alignment | TLT | treasury | bearish | 1 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=2; segments_with_same_median_sign=1; majority_threshold=4 |
| segment_sign_agreement | trend_alignment | TLT | treasury | bearish | 5 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=4; majority_threshold=4 |
| segment_sign_agreement | trend_alignment | TLT | treasury | bearish | 20 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=3; segments_with_same_median_sign=3; majority_threshold=4 |
| episode_concentration | trend_alignment | TLT | treasury | bearish |  | observations=1243; episodes=29; share_largest_episode=+0.133548; share_three_largest=+0.351569; share_threshold=+0.250000 |
| segment_sign_agreement | trend_alignment | GLD | gold | bullish | 1 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=2; segments_with_same_median_sign=2; majority_threshold=4 |
| segment_sign_agreement | trend_alignment | GLD | gold | bullish | 5 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=4; majority_threshold=4 |
| segment_sign_agreement | trend_alignment | GLD | gold | bullish | 20 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=4; majority_threshold=4 |
| episode_concentration | trend_alignment | GLD | gold | bullish |  | observations=1325; episodes=27; share_largest_episode=+0.086038; share_three_largest=+0.237736; share_threshold=+0.250000 |
| segment_sign_agreement | trend_alignment | GLD | gold | bearish | 1 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=2; segments_with_same_median_sign=2; majority_threshold=4 |
| segment_sign_agreement | trend_alignment | GLD | gold | bearish | 5 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=3; segments_with_same_median_sign=3; majority_threshold=4 |
| segment_sign_agreement | trend_alignment | GLD | gold | bearish | 20 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=3; majority_threshold=4 |
| episode_concentration | trend_alignment | GLD | gold | bearish |  | observations=1099; episodes=28; share_largest_episode=+0.098271; share_three_largest=+0.259327; share_threshold=+0.250000 |
| segment_sign_agreement | momentum_in_trend_context | SPY | equity | bullish | 1 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=3; segments_with_same_median_sign=2; majority_threshold=4 |
| segment_sign_agreement | momentum_in_trend_context | SPY | equity | bullish | 5 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=4; majority_threshold=4 |
| segment_sign_agreement | momentum_in_trend_context | SPY | equity | bullish | 20 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=5; majority_threshold=4 |
| episode_concentration | momentum_in_trend_context | SPY | equity | bullish |  | observations=1189; episodes=103; share_largest_episode=+0.050463; share_three_largest=+0.133726; share_threshold=+0.250000 |
| segment_sign_agreement | momentum_in_trend_context | SPY | equity | bearish | 1 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=3; segments_with_same_median_sign=3; majority_threshold=4 |
| segment_sign_agreement | momentum_in_trend_context | SPY | equity | bearish | 5 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=3; segments_with_same_median_sign=5; majority_threshold=4 |
| segment_sign_agreement | momentum_in_trend_context | SPY | equity | bearish | 20 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=4; majority_threshold=4 |
| episode_concentration | momentum_in_trend_context | SPY | equity | bearish |  | observations=279; episodes=63; share_largest_episode=+0.064516; share_three_largest=+0.189964; share_threshold=+0.250000 |
| segment_sign_agreement | momentum_in_trend_context | QQQ | equity | bullish | 1 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=5; segments_with_same_median_sign=4; majority_threshold=4 |
| segment_sign_agreement | momentum_in_trend_context | QQQ | equity | bullish | 5 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=5; segments_with_same_median_sign=5; majority_threshold=4 |
| segment_sign_agreement | momentum_in_trend_context | QQQ | equity | bullish | 20 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=5; segments_with_same_median_sign=5; majority_threshold=4 |
| episode_concentration | momentum_in_trend_context | QQQ | equity | bullish |  | observations=1187; episodes=115; share_largest_episode=+0.050548; share_three_largest=+0.128054; share_threshold=+0.250000 |
| segment_sign_agreement | momentum_in_trend_context | QQQ | equity | bearish | 1 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=4; majority_threshold=4 |
| segment_sign_agreement | momentum_in_trend_context | QQQ | equity | bearish | 5 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=4; majority_threshold=4 |
| segment_sign_agreement | momentum_in_trend_context | QQQ | equity | bearish | 20 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=4; majority_threshold=4 |
| episode_concentration | momentum_in_trend_context | QQQ | equity | bearish |  | observations=288; episodes=52; share_largest_episode=+0.093750; share_three_largest=+0.208333; share_threshold=+0.250000 |
| segment_sign_agreement | momentum_in_trend_context | IWM | equity | bullish | 1 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=5; segments_with_same_median_sign=3; majority_threshold=4 |
| segment_sign_agreement | momentum_in_trend_context | IWM | equity | bullish | 5 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=5; segments_with_same_median_sign=5; majority_threshold=4 |
| segment_sign_agreement | momentum_in_trend_context | IWM | equity | bullish | 20 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=5; segments_with_same_median_sign=5; majority_threshold=4 |
| episode_concentration | momentum_in_trend_context | IWM | equity | bullish |  | observations=874; episodes=130; share_largest_episode=+0.067506; share_three_largest=+0.172769; share_threshold=+0.250000 |
| segment_sign_agreement | momentum_in_trend_context | IWM | equity | bearish | 1 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=2; segments_with_same_median_sign=2; majority_threshold=4 |
| segment_sign_agreement | momentum_in_trend_context | IWM | equity | bearish | 5 | full_window_mean_delta_sign=-; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=3; majority_threshold=4 |
| segment_sign_agreement | momentum_in_trend_context | IWM | equity | bearish | 20 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=2; segments_with_same_median_sign=3; majority_threshold=4 |
| episode_concentration | momentum_in_trend_context | IWM | equity | bearish |  | observations=382; episodes=71; share_largest_episode=+0.083770; share_three_largest=+0.196335; share_threshold=+0.250000 |
| segment_sign_agreement | momentum_in_trend_context | TLT | treasury | bullish | 1 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=2; segments_with_same_median_sign=3; majority_threshold=4 |
| segment_sign_agreement | momentum_in_trend_context | TLT | treasury | bullish | 5 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=2; segments_with_same_median_sign=4; majority_threshold=4 |
| segment_sign_agreement | momentum_in_trend_context | TLT | treasury | bullish | 20 | full_window_mean_delta_sign=+; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=3; segments_with_same_median_sign=4; majority_threshold=4 |
| episode_concentration | momentum_in_trend_context | TLT | treasury | bullish |  | observations=599; episodes=85; share_largest_episode=+0.073456; share_three_largest=+0.175292; share_threshold=+0.250000 |
| segment_sign_agreement | momentum_in_trend_context | TLT | treasury | bearish | 1 | full_window_mean_delta_sign=-; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=2; segments_with_same_median_sign=2; majority_threshold=4 |
| segment_sign_agreement | momentum_in_trend_context | TLT | treasury | bearish | 5 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=3; segments_with_same_median_sign=3; majority_threshold=4 |
| segment_sign_agreement | momentum_in_trend_context | TLT | treasury | bearish | 20 | full_window_mean_delta_sign=-; full_window_median_delta_sign=-; segments=5; segments_with_same_mean_sign=3; segments_with_same_median_sign=2; majority_threshold=4 |
| episode_concentration | momentum_in_trend_context | TLT | treasury | bearish |  | observations=696; episodes=85; share_largest_episode=+0.086207; share_three_largest=+0.222701; share_threshold=+0.250000 |
| segment_sign_agreement | momentum_in_trend_context | GLD | gold | bullish | 1 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=4; segments_with_same_median_sign=3; majority_threshold=4 |
| segment_sign_agreement | momentum_in_trend_context | GLD | gold | bullish | 5 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=3; segments_with_same_median_sign=3; majority_threshold=4 |
| segment_sign_agreement | momentum_in_trend_context | GLD | gold | bullish | 20 | full_window_mean_delta_sign=+; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=2; segments_with_same_median_sign=3; majority_threshold=4 |
| episode_concentration | momentum_in_trend_context | GLD | gold | bullish |  | observations=787; episodes=91; share_largest_episode=+0.048285; share_three_largest=+0.141042; share_threshold=+0.250000 |
| segment_sign_agreement | momentum_in_trend_context | GLD | gold | bearish | 1 | full_window_mean_delta_sign=-; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=2; segments_with_same_median_sign=4; majority_threshold=4 |
| segment_sign_agreement | momentum_in_trend_context | GLD | gold | bearish | 5 | full_window_mean_delta_sign=-; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=2; segments_with_same_median_sign=5; majority_threshold=4 |
| segment_sign_agreement | momentum_in_trend_context | GLD | gold | bearish | 20 | full_window_mean_delta_sign=-; full_window_median_delta_sign=+; segments=5; segments_with_same_mean_sign=3; segments_with_same_median_sign=4; majority_threshold=4 |
| episode_concentration | momentum_in_trend_context | GLD | gold | bearish |  | observations=496; episodes=90; share_largest_episode=+0.098790; share_three_largest=+0.223790; share_threshold=+0.250000 |
| gate_partition_signs | trend_alignment | SPY | equity | bullish | 1 | retained_n=1166; removed_n=543; opposite_n=0; retained_median_delta_sign=-; removed_median_delta_sign=+; retained_mean_delta_sign=+; removed_mean_delta_sign=- |
| gate_partition_signs | trend_alignment | SPY | equity | bullish | 5 | retained_n=1166; removed_n=543; opposite_n=0; retained_median_delta_sign=-; removed_median_delta_sign=+; retained_mean_delta_sign=-; removed_mean_delta_sign=+ |
| gate_partition_signs | trend_alignment | SPY | equity | bullish | 20 | retained_n=1166; removed_n=543; opposite_n=0; retained_median_delta_sign=-; removed_median_delta_sign=+; retained_mean_delta_sign=-; removed_mean_delta_sign=+ |
| gate_partition_signs | trend_alignment | SPY | equity | bearish | 1 | retained_n=270; removed_n=454; opposite_n=0; retained_median_delta_sign=+; removed_median_delta_sign=-; retained_mean_delta_sign=+; removed_mean_delta_sign=- |
| gate_partition_signs | trend_alignment | SPY | equity | bearish | 5 | retained_n=270; removed_n=454; opposite_n=0; retained_median_delta_sign=+; removed_median_delta_sign=-; retained_mean_delta_sign=+; removed_mean_delta_sign=- |
| gate_partition_signs | trend_alignment | SPY | equity | bearish | 20 | retained_n=270; removed_n=454; opposite_n=0; retained_median_delta_sign=+; removed_median_delta_sign=-; retained_mean_delta_sign=+; removed_mean_delta_sign=- |
| gate_partition_signs | trend_alignment | QQQ | equity | bullish | 1 | retained_n=1171; removed_n=561; opposite_n=0; retained_median_delta_sign=-; removed_median_delta_sign=+; retained_mean_delta_sign=-; removed_mean_delta_sign=+ |
| gate_partition_signs | trend_alignment | QQQ | equity | bullish | 5 | retained_n=1171; removed_n=561; opposite_n=0; retained_median_delta_sign=-; removed_median_delta_sign=+; retained_mean_delta_sign=+; removed_mean_delta_sign=- |
| gate_partition_signs | trend_alignment | QQQ | equity | bullish | 20 | retained_n=1171; removed_n=561; opposite_n=0; retained_median_delta_sign=-; removed_median_delta_sign=+; retained_mean_delta_sign=-; removed_mean_delta_sign=+ |
| gate_partition_signs | trend_alignment | QQQ | equity | bearish | 1 | retained_n=284; removed_n=438; opposite_n=0; retained_median_delta_sign=+; removed_median_delta_sign=-; retained_mean_delta_sign=+; removed_mean_delta_sign=- |
| gate_partition_signs | trend_alignment | QQQ | equity | bearish | 5 | retained_n=284; removed_n=438; opposite_n=0; retained_median_delta_sign=+; removed_median_delta_sign=-; retained_mean_delta_sign=+; removed_mean_delta_sign=- |
| gate_partition_signs | trend_alignment | QQQ | equity | bearish | 20 | retained_n=284; removed_n=438; opposite_n=0; retained_median_delta_sign=-; removed_median_delta_sign=+; retained_mean_delta_sign=+; removed_mean_delta_sign=- |
| gate_partition_signs | trend_alignment | IWM | equity | bullish | 1 | retained_n=852; removed_n=728; opposite_n=0; retained_median_delta_sign=-; removed_median_delta_sign=+; retained_mean_delta_sign=-; removed_mean_delta_sign=+ |
| gate_partition_signs | trend_alignment | IWM | equity | bullish | 5 | retained_n=852; removed_n=728; opposite_n=0; retained_median_delta_sign=-; removed_median_delta_sign=+; retained_mean_delta_sign=-; removed_mean_delta_sign=+ |
| gate_partition_signs | trend_alignment | IWM | equity | bullish | 20 | retained_n=852; removed_n=728; opposite_n=0; retained_median_delta_sign=-; removed_median_delta_sign=+; retained_mean_delta_sign=-; removed_mean_delta_sign=+ |
| gate_partition_signs | trend_alignment | IWM | equity | bearish | 1 | retained_n=370; removed_n=480; opposite_n=0; retained_median_delta_sign=+; removed_median_delta_sign=-; retained_mean_delta_sign=+; removed_mean_delta_sign=- |
| gate_partition_signs | trend_alignment | IWM | equity | bearish | 5 | retained_n=370; removed_n=480; opposite_n=0; retained_median_delta_sign=+; removed_median_delta_sign=-; retained_mean_delta_sign=-; removed_mean_delta_sign=+ |
| gate_partition_signs | trend_alignment | IWM | equity | bearish | 20 | retained_n=370; removed_n=480; opposite_n=0; retained_median_delta_sign=-; removed_median_delta_sign=+; retained_mean_delta_sign=-; removed_mean_delta_sign=+ |
| gate_partition_signs | trend_alignment | TLT | treasury | bullish | 1 | retained_n=582; removed_n=579; opposite_n=0; retained_median_delta_sign=+; removed_median_delta_sign=-; retained_mean_delta_sign=+; removed_mean_delta_sign=- |
| gate_partition_signs | trend_alignment | TLT | treasury | bullish | 5 | retained_n=582; removed_n=579; opposite_n=0; retained_median_delta_sign=+; removed_median_delta_sign=0; retained_mean_delta_sign=-; removed_mean_delta_sign=+ |
| gate_partition_signs | trend_alignment | TLT | treasury | bullish | 20 | retained_n=582; removed_n=579; opposite_n=0; retained_median_delta_sign=-; removed_median_delta_sign=+; retained_mean_delta_sign=-; removed_mean_delta_sign=+ |
| gate_partition_signs | trend_alignment | TLT | treasury | bearish | 1 | retained_n=681; removed_n=562; opposite_n=0; retained_median_delta_sign=+; removed_median_delta_sign=-; retained_mean_delta_sign=-; removed_mean_delta_sign=+ |
| gate_partition_signs | trend_alignment | TLT | treasury | bearish | 5 | retained_n=681; removed_n=562; opposite_n=0; retained_median_delta_sign=-; removed_median_delta_sign=+; retained_mean_delta_sign=-; removed_mean_delta_sign=+ |
| gate_partition_signs | trend_alignment | TLT | treasury | bearish | 20 | retained_n=681; removed_n=562; opposite_n=0; retained_median_delta_sign=-; removed_median_delta_sign=+; retained_mean_delta_sign=-; removed_mean_delta_sign=+ |
| gate_partition_signs | trend_alignment | GLD | gold | bullish | 1 | retained_n=776; removed_n=549; opposite_n=0; retained_median_delta_sign=0; removed_median_delta_sign=-; retained_mean_delta_sign=-; removed_mean_delta_sign=+ |
| gate_partition_signs | trend_alignment | GLD | gold | bullish | 5 | retained_n=776; removed_n=549; opposite_n=0; retained_median_delta_sign=+; removed_median_delta_sign=-; retained_mean_delta_sign=-; removed_mean_delta_sign=+ |
| gate_partition_signs | trend_alignment | GLD | gold | bullish | 20 | retained_n=776; removed_n=549; opposite_n=0; retained_median_delta_sign=-; removed_median_delta_sign=+; retained_mean_delta_sign=-; removed_mean_delta_sign=+ |
| gate_partition_signs | trend_alignment | GLD | gold | bearish | 1 | retained_n=485; removed_n=614; opposite_n=0; retained_median_delta_sign=+; removed_median_delta_sign=-; retained_mean_delta_sign=+; removed_mean_delta_sign=- |
| gate_partition_signs | trend_alignment | GLD | gold | bearish | 5 | retained_n=485; removed_n=614; opposite_n=0; retained_median_delta_sign=+; removed_median_delta_sign=-; retained_mean_delta_sign=+; removed_mean_delta_sign=- |
| gate_partition_signs | trend_alignment | GLD | gold | bearish | 20 | retained_n=485; removed_n=614; opposite_n=0; retained_median_delta_sign=+; removed_median_delta_sign=-; retained_mean_delta_sign=+; removed_mean_delta_sign=- |

## Limitations

- Every number here is a regrouping of the frozen Baseline Study v1 rows; no new market data was fetched and no forward return was computed.
- Forward windows overlap (up to 4 of 5 bars at h5 and 19 of 20 at h20); counts are not independent trials.
- episode_count, episode lengths and the episode-start view are descriptive reading aids; none is an effective sample size or an independence correction, and the episode-start view is a secondary sampling view, not a replacement for the Phase R results.
- The segment, episode-share and gate-partition decision aids are predeclared descriptive rules for the human review gate; they are not significance tests, confidence criteria, robustness proofs or acceptance thresholds, and no change is selected by them.
- Asset class is metadata for reading sign patterns; nothing is pooled by class and no class-specific parameter exists.
- The two level hypotheses share the SMA20/SMA50 relation; momentum_in_trend_context gates the same trend state with RSI14, so agreement between them is not independent confirmation.
- Crossover events are one bar each and few; their listing supports a later decision, not a conclusion here.
- RAW price basis, provider revisions/back-fills, the absence of an exchange calendar and the retrospective nature of the source study all carry over from Baseline Study v1.
- Data from 2025-03-01 onward was not read; the source rows end at 2024-12-31 and any later row is refused.
- Nothing here is a profitability, edge, accuracy or significance claim, and no hypothesis, threshold or feature was changed.
