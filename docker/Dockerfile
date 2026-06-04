FROM python:3.11

WORKDIR /app

# 换 Debian apt 源为清华源
#RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
#    && sed -i 's|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources
#
#RUN apt-get update \
#    && apt-get install -y --no-install-recommends \
#        libreoffice \
#        build-essential \
#        libmupdf-dev \
#        pkg-config \
#    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# cinrad 1.9.3 imports numpy from setup.py while pip is preparing metadata.
# Install it without dependencies first; the final command installs all
# dependencies normally so their own build isolation remains enabled.
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
    && python -m pip install --no-cache-dir numpy==1.26.4 \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
    && python -m pip install --no-cache-dir --no-build-isolation --no-deps \
        cinrad==1.9.3 \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
    && python -m pip install --no-cache-dir -r requirements.txt \
        -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY . .

EXPOSE 8080

CMD ["python", "manage.py", "runserver", "0.0.0.0:8080", "--noreload"]
