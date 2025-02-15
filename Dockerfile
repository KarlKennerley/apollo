FROM python:3.10 AS builder

RUN pip install --user pipenv

# Tell pipenv to create venv in the current directory
ENV PIPENV_VENV_IN_PROJECT=1

# only copy in lockfile - install from locked deps
COPY Pipfile.lock /app/Pipfile.lock

WORKDIR /app

RUN /root/.local/bin/pipenv sync

FROM python:3.10 AS runtime

WORKDIR /app

# copy venv into runtime
COPY --from=builder /app/.venv/ /app/.venv/

# add venv to path
ENV PATH=".venv/bin:$PATH"

# copy in everything
COPY . /app

# build default alembic config into container, we rarely want to change this
RUN /bin/bash -c 'if [[ ! -f alembic.ini ]]; then mv alembic.example.ini alembic.ini; fi'

CMD [ "python", "apollo.py" ] 