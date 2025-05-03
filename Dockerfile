# ベースイメージを選択 (アプリで使用しているPythonバージョンに合わせる)
FROM python:3.11-slim

# 環境変数 PORT を設定 (Cloud Run が期待する)
ENV PORT=8080
# Streamlit関連の環境変数 (推奨)
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=false
ENV STREAMLIT_SERVER_ENABLE_CORS=false

# 作業ディレクトリ設定・作成
WORKDIR /app

# 依存関係ファイルをコピー
COPY requirements.txt ./

# 依存関係をインストール (OSパッケージが必要な場合も考慮)
# 例: RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードをコピー (必要なファイルのみ)
COPY app.py ./
# 他に必要なファイルがあればここに追加 (例: CSSファイルなど)
# COPY styles.css ./

# ポートを公開 (ドキュメント目的)
EXPOSE ${PORT}

# Streamlitサーバーを起動
CMD ["streamlit", "run", "app.py", "--server.port", "${PORT}"]