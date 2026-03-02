# Domain Info Checker

Domain Info Checker is a small utility that:

- Reads a CSV file containing domains in the **first column**
- Validates and normalizes each domain
- Calls **WhoisXML API – Domain Info API**
- Extracts selected fields from the API response
- Writes those fields back into the same CSV file
- Logs results and errors to the console
- Saves the CSV upon completion

---

# What It Extracts

For each valid domain, the script retrieves:

- `createdDate`
- `registrarName`
- `Registrant_name`
- `Registrant_country`

These values are written into their respective columns in the same CSV file.

---

# How It Works

For each row in the CSV:

1. Reads the first column.
2. Accepts domains in formats like:
   - `example.com`
   - `www.example.com`
   - `https://example.com`
   - `http://www.example.com/path?query=1`
3. Normalizes the domain:
   - Removes scheme (`http://`, `https://`)
   - Removes `www.`
   - Removes paths and query parameters
   - Converts to lowercase
4. Validates that it looks like a proper `label.tld` domain.
5. Calls:

```
https://domain-info.whoisxmlapi.com/api/v1
```

With parameters:
- `apiKey`
- `domainName`
- `outputFormat=JSON`

6. If successful:
   - Writes extracted values into the CSV
   - Prints them to console
7. If failed:
   - Prints the API error
   - Moves to the next domain

At the end:
```
Completed. Updated CSV saved: your-file.csv
```

---

# Files

You should have:

```
domain_info_checker.py
run-domain-info-checker.sh
README.md
```

---

# Requirements

- macOS or Linux
- Python 3 installed
- Internet access
- WhoisXML API key with access to **Domain Info API**

---

# Setup

## 1. Make the shell script executable

```bash
chmod +x run-domain-info-checker.sh
```

---

## 2. Provide your API key

The script uses exactly ONE environment variable:

```
WHOISXMLAPI_API_KEY
```

You can run it safely in one command:

```bash
WHOISXMLAPI_API_KEY="YOUR_API_KEY" ./run-domain-info-checker.sh domains.csv
```

Or export once:

```bash
export WHOISXMLAPI_API_KEY="YOUR_API_KEY"
./run-domain-info-checker.sh domains.csv
```

No other API key variables are used.

---

# Usage

```
./run-domain-info-checker.sh <input.csv>
```

Example:

```bash
./run-domain-info-checker.sh domains-list-new.csv
```

The script updates the CSV **in place** (overwrites the same file).

---

# CSV Format

## Input

- Domains must be in the **first column**
- A header row is allowed but not required

Example:

```csv
domain
example.com
https://google.com
invalid-domain
```

---

## Output

If missing, these columns are added:

- createdDate
- registrarName
- Registrant_name
- Registrant_country

If a domain is invalid, it is skipped.

If an API call fails, the row remains unchanged and an error is printed.

---

# Example Console Output

Success:

```
[example.com] OK | createdDate=1995-08-14T04:00:00Z | registrarName=Example Registrar | Registrant_name=John Doe | Registrant_country=US
```

Error:

```
[example.com] ERROR: HTTP 403: messages=Access restricted. Check the credits balance or enter the correct API key.
```

Completion:

```
Completed. Updated CSV saved: domains.csv
```

---

# Troubleshooting

## Permission denied

If you see:

```
zsh: permission denied: ./run-domain-info-checker.sh
```

Run:

```bash
chmod +x run-domain-info-checker.sh
```

Or bypass:

```bash
bash run-domain-info-checker.sh domains.csv
```

---

## HTTP 403 Error

If you see:

```
HTTP 403: Access restricted...
```

This means:

- API key is incorrect
- Domain Info API is not enabled for your account
- Insufficient credits
- API key has IP restrictions

To test the key manually:

```bash
curl -G "https://domain-info.whoisxmlapi.com/api/v1" \
  --data-urlencode "apiKey=$WHOISXMLAPI_API_KEY" \
  --data-urlencode "domainName=example.com" \
  --data-urlencode "outputFormat=JSON"
```

If this returns 403, the issue is account/credits/key-related, not script-related.

---

# Notes

- The script overwrites the input CSV.
- Domains are normalized and validated.
- IDNs are supported via IDNA (punycode).
- Missing or redacted fields are written as blank cells.
- Only one environment variable is used for the API key.

---

# API Documentation

Domain Info API documentation:

https://domain-info.whoisxmlapi.com/api