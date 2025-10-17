# word-template-test

```bash
    sudo apt install python3
    sudo apt install python3-venv
    sudo apt install python3-pip
    git clone https://github.com/Kirillex22/word-template-test.git
    cd word-template-test
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    uvicorn main:app --host 0.0.0.0 --port 8000
```