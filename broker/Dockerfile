FROM python:3.11-slim

WORKDIR /srv

COPY broker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY broker/ /srv/broker/
# The manifest parser is shared with the bot so both agree on what a
# declaration means; the broker imports it directly rather than duplicating it.
COPY dopplerbot/plugins/manifest.py /srv/dopplerbot/plugins/manifest.py
COPY dopplerbot/__init__.py /srv/dopplerbot/__init__.py
RUN touch /srv/dopplerbot/plugins/__init__.py

ENV PYTHONPATH=/srv
CMD ["python", "-m", "broker.main"]
