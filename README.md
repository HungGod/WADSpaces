PWA's but without the browser.

## System Requirements
 - python >= 3.14.0 
 - Linux (I haven't tested this on any other OS)

## Setup / Run

# 1. Create venv.
```bash
python -m venv .venv
```

# 2. Activate venv
```bash
# Linux
source .venv/bin/activate
```

# 3. Install requirements
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

# 4. Create resources.json

Create a file (e.g., packager/resources.json) containing the websites you want to wrap:
```json
[
    {
        "app_url": "https://example.com",
        "app_name": "Example"
    },
    {
        "app_url": "https://example2.com",
        "app_name": "Example2"
    }
]
```
app_url – the website you want to wrap
app_name – how the app will be named on your system

# 5. Run the packager script.
```bash
# make sure venv is activated and you're terminal is inside the project
python packager/packager.py -i 'packager/resources.json'

```

# 6. Launch the web apps

Apps will be downloaded directly on the desktop, ready to launch. 

