FROM apify/actor-python-playwright:3.12

USER root

RUN apt-get update \
 && apt-get install -y poppler-utils \
 && rm -rf /var/lib/apt/lists/*

USER myuser

COPY --chown=myuser:myuser requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=myuser:myuser . ./

RUN python -m compileall -q src/

CMD ["python", "-m", "src"]
