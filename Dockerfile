# ---- Base image ----
FROM python:3.11-slim

# ---- Set working directory ----
WORKDIR /app

# ---- Copy dependency file first (for caching) ----
COPY requirements.txt .

# ---- Install Python dependencies ----
RUN pip install --no-cache-dir -r requirements.txt

# ---- Copy the rest of the bot files ----
COPY . .

# ---- Expose Koyeb port ----
ENV PORT=8080
EXPOSE 8080

# ---- Run your bot ----
CMD ["python", "broadcast_bot.py"]
