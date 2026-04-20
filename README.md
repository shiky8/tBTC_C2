# tBTC C2 - Web3 Bitcoin Testnet Command & Control

A lightweight, stealthy **Command & Control (C2)** framework that uses **Bitcoin Testnet (tBTC)** as its communication channel via `OP_RETURN` messages.

All commands and responses are embedded directly into the Bitcoin blockchain, making the C2 extremely difficult to block or detect compared to traditional HTTP/DNS C2s.

---

## Overview

- **Attacker (Controller)** sends commands to the implant.
- **Target (Implant)** executes shell commands and exfiltrates output back via Bitcoin.
- Communication is **one-way per transaction** (push model) using compressed `OP_RETURN` data.
- Fully functional on **Bitcoin Testnet** — safe for testing and research.

### Features

- LZMA compression + smart fitting for messages up to ~200+ characters
- Automatic UTXO management and change handling
- Pending UTXO tracking for fast follow-up transactions
- Subprocess command execution on target
- Simple monitoring loops
- Testnet wallet generator included

---

## Files

| File                        | Role                          | Description |
|----------------------------|-------------------------------|-----------|
| `tBTC_wallet_generator.py` | Wallet Creation              | Generates fresh testnet wallets + shows faucets |
| `tbtc_c2_atk.py`           | Attacker (Sender)            | Main attacker script to send commands |
| `tbtc_c2_targ_v2.py`       | Target/Implant (Receiver)    | Full C2 implant — receives, executes, and replies |
| `tbtc_c2_atk_mon.py`       | Attacker Monitor             | Simplified monitoring version for attacker |

---

## Quick Start

### 1. Generate Wallets

```bash
python tBTC_wallet_generator.py
```

Get free tBTC from:
- https://coinfaucet.eu/en/btc-testnet/
- https://tbtc.bitaps.com/
- https://bitcoinfaucet.uo1.net/

**Fund both attacker and target addresses.**

### 2. Target / Implant (`tbtc_c2_targ_v2.py`)

Update the private key and addresses inside the script, then run:

```bash
python tbtc_c2_targ_v2.py
```

The implant will:
- Monitor the target address for incoming commands
- Execute received commands via `subprocess`
- Automatically send the output back to the attacker

**Stop command**: `stopeme`

### 3. Attacker (`tbtc_c2_atk.py`)

```bash
python tbtc_c2_atk.py
```

Type commands — they will be compressed and sent via Bitcoin Testnet transaction.

---

## Configuration (Important)

Update these variables in each script:

**Attacker side (`tbtc_c2_atk.py` & `tbtc_c2_atk_mon.py`):**
```python
wif  = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"  # Attacker WIF
to   = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"                    # Target address
addr = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"                    # Attacker address (for monitoring)
```

**Target side (`tbtc_c2_targ_v2.py`):**
```python
wif   = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"  # Target WIF
to    = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"                    # Attacker address
addr  = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"                    # Target address (monitoring)
```

> **Never use real Bitcoin (mainnet) with this code.**

---
## Demo


https://github.com/user-attachments/assets/303774c8-9dd6-4d4c-ad1b-0754e3db7ee4


---
## How It Works

1. Messages are LZMA-compressed.
2. If too big, only the beginning is sent with `1/2|` header.
3. A dust output (`546 sats`) is sent to the receiver.
4. `OP_RETURN` carries the payload (max ~80 bytes).
5. Both sides poll `mempool.space/testnet/api` for new transactions.

---

## Security / OPSEC Notes

- Extremely low throughput (~1 command every 10–60 seconds depending on confirmation speed).
- All activity is public on the blockchain (but encrypted/compressed).
- Use fresh wallets for each operation.
- This is for **educational and research purposes only**.

---

## Limitations

- Slow (Bitcoin block time + mempool propagation)
- Message size limited (~200 chars after compression)
- No full encryption (only compression) — add your own layer if needed
- Testnet only (intentionally)

---

## Legal & Disclaimer

This project is for **educational and security research purposes only**.  
Using this on Bitcoin mainnet or without authorization may violate laws in your jurisdiction.

**Use responsibly on Testnet.**

---

## Future Improvements

- AES encryption layer
- Multi-part message support (`1/3|`, `2/3|`, etc.)
- Better error handling & reconnection
- Stealthier fee & dust strategies

---

**Made for Web3 Red Teaming & Blockchain C2 research**

Happy hacking (on testnet)! 
