name: Flask CI

on:
  push:
    branches:
      - main
  pull_request:
    branches:
      - main

jobs:
  build-test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v3

    # Установка Python
    - name: Setup Python
      uses: actions/setup-python@v5
      with:
        python-version: '3.11'

    # Встановлення залежностей
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt

    # Запуск тестів (наприклад pytest)
    - name: Run tests
      run: |
        pytest
