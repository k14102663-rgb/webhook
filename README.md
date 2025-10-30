# webhook
webhook tatum Crypto backend — balances &amp; history + batch per chain

# Crypto Backend — Multi‑Chain Balances & Transaction History API

A FastAPI backend that provides unified access to **balances** and **transaction histories** across major blockchains:

* **Ethereum (ETH)**
* **BNB Smart Chain (BSC)**
* **Tron (TRX)**
* **Bitcoin (BTC)**
* **Solana (SOL)**

It also includes **USDT (ERC20/BEP20/TRC20/SPL)** tracking and multi-address batch querying.

---

## ✅ Features

### **Balance Endpoints**

* Fetch native coin balances (ETH, BNB, TRX, BTC, SOL)
* Batch requests for up to 100 addresses per chain
* Automatic validation for each chain's address format

### **History Endpoints**

* **USDT ERC20/BEP20** history via blockchain logs
* **TRON** normal and TRC20 USDT history with pagination
* **Bitcoin** transaction history with paging
* **Solana** history via RPC with options:

  * Only token-transfer instructions
  * Only USDT (SPL Token Program)

### **Technical Highlights**

* Built with **FastAPI**
* Chain‑specific RPC integrations using **Tatum Blockchain API**
* Integrated retry logic with backoff
* Clean JSON responses with timestamping
* Fully typed models via **Pydantic**

---

## 🚀 Installation

```bash
# Clone repository
git clone https://github.com/yourname/yourrepo.git
cd yourrepo

# (Recommended) Create virtual env
python -m venv .venv
source .venv/bin/activate     # Linux/Mac
.venv\Scripts\activate       # Windows

# Install dependencies
pip install -r requirements.txt
```

---

## 🔑 Configuration

The project uses **Tatum API Gateway** for RPC and REST endpoints.

Edit your **TATUM_API_KEY** inside `app.py`:

```python
TATUM_API_KEY = "your-api-key-here"
```

You can obtain a free key at:
[https://tatum.io](https://tatum.io)

---

## ▶️ Running the Server

```bash
uvicorn app:app --host 0.0.0.0 --port 8080 --reload
```

Server starts at:

```
http://localhost:8080
+
http://localhost:8080/docs
```

Health check:

```
GET /test
```

---

## 📡 API Overview

### **1. ETH — Batch Balance**

```
POST /eth/balance_batch
```

Body:

```json
{
  "addresses": ["0x..."]
}
```

### **2. BSC — Batch Balance**

```
POST /bsc/balance_batch
```

### **3. Tron, Bitcoin, Solana Batch Balances**

```
POST /tron/balance_batch
POST /btc/balance_batch
POST /solana/balance_batch
```

---

### **USDT Transaction History (ETH/BSC)**

```
POST /eth/history_usdt
POST /bsc/history_usdt
```

Body:

```json
{
  "address": "0x...",
  "from_block": "0x0",
  "to_block": "latest",
  "limit_logs": 2000
}
```

---

### **Tron History (TRX + USDT TRC20)**

```
POST /tron/history
POST /tron/history_usdt
```

---

### **Bitcoin History**

```
POST /btc/history
```

---

### **Solana History (SPL/SOL/USDT)**

```
POST /solana/history_batch
```

Options:

* `only_token_transfers: true`
* `only_usdt: true`

---

## 📁 Project Structure

```
app.py              # Main FastAPI application
requirements.txt    # Python dependencies
README.md           # Documentation
```

---

## 🧩 Dependencies

* FastAPI
* Uvicorn
* Pydantic
* Requests

Install via:

```bash
pip install fastapi uvicorn pydantic requests
```

---

## ⚠️ Notes

* Tatum API rate limits may apply.
* USDT transfer filtering on ETH/BSC uses raw log scanning.
* For Solana USDT, the script resolves the associated token account (ATA).

---

## 📜 License

MIT License

---

## 🤝 Contributing

Pull requests and improvements are welcome!

---

## ⭐ Support

If this project helps you — please star the repo!

---

✔ file `app.py`
