# Biograph — TLS & Local HTTPS Setup

Running your Biograph backend server over HTTPS ensures all logged events, search queries, and access tokens are encrypted over the network. Since Biograph is designed to run locally, you can set up a local self-signed Certificate Authority (CA).

This guide walks you through:
1. Creating a local Certificate Authority (CA) and signing a certificate.
2. Configuring the Biograph backend server to use TLS.
3. Configuring sensors to trust your local CA.

---

## 1. Create a Local Certificate Authority & Certificate

You can use `openssl` to generate a local CA and sign a certificate for your server (e.g. `127.0.0.1` or `localhost`).

### Step A: Generate the root CA key and certificate
This certificate acts as your personal local authority.

```bash
# Generate root CA private key
openssl genrsa -out rootCA.key 4096

# Generate root CA certificate (valid for 10 years)
openssl req -x509 -new -nodes -key rootCA.key -sha256 -days 3650 -out rootCA.pem \
  -subj "/C=US/ST=State/L=City/O=Local Dev/CN=Biograph Local Root CA"
```

### Step B: Create a certificate signing request (CSR) and sign it
Create a configuration file `server.ext` to specify the Subject Alternative Names (SAN) for localhost:

```ini
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
IP.1 = 127.0.0.1
```

Now, generate the server key, CSR, and sign the certificate:

```bash
# Generate server private key
openssl genrsa -out server.key 2048

# Generate CSR
openssl req -new -key server.key -out server.csr \
  -subj "/C=US/ST=State/L=City/O=Local Dev/CN=localhost"

# Sign the server certificate using rootCA (valid for 2 years)
openssl x509 -req -in server.csr -CA rootCA.pem -CAkey rootCA.key \
  -CAcreateserial -out server.crt -days 730 -sha256 -extfile server.ext
```

You now have the two files needed for the server:
- **`server.crt`**: The server certificate (PEM).
- **`server.key`**: The server private key (PEM).

And the root certificate to import on clients:
- **`rootCA.pem`**: The CA certificate to trust.

---

## 2. Configure Biograph Backend

Move `server.crt` and `server.key` to a secure directory (e.g. `~/.config/biograph/`) and update your root `config.toml` file:

```toml
[server]
host    = "0.0.0.0"      # bind to all addresses
port    = 8000
token   = "your-secret-token"

[tls]
enabled  = true
certfile = "/home/yourusername/.config/biograph/server.crt"
keyfile  = "/home/yourusername/.config/biograph/server.key"
```

Restart the server:
```bash
uv run biograph-server
```
Uvicorn will automatically load the certificates and run over HTTPS. You can access the interface at `https://localhost:8000`.

---

## 3. Configure Sensors to Trust the CA

Because python scripts and browsers do not trust self-signed certificates by default, you must configure them to trust your `rootCA.pem` file.

### A. System-wide trust (Recommended)
The easiest way is to import `rootCA.pem` directly into your operating system's trust store.

* **Arch Linux / Fedora / RHEL**:
  ```bash
  sudo cp rootCA.pem /etc/ca-certificates/trust-source/anchors/biographCA.crt
  sudo update-ca-trust
  ```
* **Ubuntu / Debian**:
  ```bash
  sudo cp rootCA.pem /usr/local/share/ca-certificates/biographCA.crt
  sudo update-ca-certificates
  ```
* **macOS**:
  Double-click `rootCA.pem`, import it into the **Keychain Access** app under the *System* keychain, double-click it, expand *Trust*, and set *When using this certificate* to **Always Trust**.

Once imported system-wide, Chrome, Safari, and system commands will automatically trust the Biograph server without further configuration.

### B. Python Sensors (`bio` CLI & Zsh Sensor)
Python's HTTP library (`httpx`) respects the `SSL_CERT_FILE` or `REQUESTS_CA_BUNDLE` environment variables. If you did not install the CA system-wide:

Add this to your `~/.zshrc` or shell configuration:
```bash
export SSL_CERT_FILE="/path/to/rootCA.pem"
```
Or run the commands directly with it:
```bash
SSL_CERT_FILE="/path/to/rootCA.pem" bio log "Test note"
```

### C. Chrome Browser Extension
If you did not install the CA system-wide, Chrome will block extension requests to `https://127.0.0.1:8000` with connection errors. To fix this:
1. Open Chrome and navigate to `https://127.0.0.1:8000/health`.
2. Chrome will show a "Your connection is not private" warning.
3. Click **Advanced** -> **Proceed to localhost (unsafe)**.
Chrome will temporarily allow connections to this origin, enabling the extension to sync events successfully.
