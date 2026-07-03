FROM python:3.12-slim

WORKDIR /app

COPY . user_agent/
WORKDIR /app/user_agent

RUN if [ -f requirements.txt ]; then \
        pip install --no-cache-dir -r requirements.txt; \
    else \
        echo "No requirements.txt found"; \
    fi

# ResponsesHostServer serves the OpenAI-compatible Responses protocol on 8088 -
# the port the Foundry hosting runtime invokes.
EXPOSE 8088

CMD ["python", "main.py"]
