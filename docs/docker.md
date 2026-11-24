# Run NIH Grant Matcher from the published Docker image

The image `ghcr.io/jrmatherly/nih-grant-matcher` holds the dashboard and the command-line tool. It is public, so you do not need to sign in to pull it, and you do not need Python, uv, or a clone of this repository to run it.

## Before you begin

- Install [Docker Desktop](https://docs.docker.com/get-started/get-docker/) or Docker Engine. Start it.
- The image supports `linux/amd64` and `linux/arm64`. It runs on Intel and Apple silicon Macs, Windows with WSL 2, and Linux.
- The image is about 860 MB.
- The tool calls public NIH and Grants.gov services, so the container needs internet access.

## Quick start

1. Make a folder for the results and go into it:

   ```bash
   mkdir -p nih-grant-matcher/data nih-grant-matcher/outputs nih-grant-matcher/digests
   cd nih-grant-matcher
   ```

2. Start the dashboard:

   ```bash
   docker run -d --name nih-grant-matcher \
     -p 127.0.0.1:8501:8501 \
     -v "$PWD/data:/app/data" \
     -v "$PWD/outputs:/app/outputs" \
     -v "$PWD/digests:/app/digests" \
     ghcr.io/jrmatherly/nih-grant-matcher:latest
   ```

   In Windows PowerShell, write the command on one line and use `${PWD}` in place of `$PWD`.

3. Open http://localhost:8501. For the controls, see [Use the NIH Grant Matcher dashboard](dashboard.md).

4. In the sidebar, select **Run Search**. The first search takes a few seconds for the NIH Guide. The **grants.gov** source makes one request for each opportunity, so the default of 500 rows takes about three minutes.

The port is published on `127.0.0.1` only. The dashboard has no login and takes file paths as input, so do not publish it on a public address.

## Start with Docker Compose

Use this method when you have a clone of the repository. `compose.yaml` sets the port, the folders, and the restart policy.

```bash
git clone https://github.com/jrmatherly/Research-Grant-Finder-Agent.git
cd Research-Grant-Finder-Agent
docker compose pull
docker compose up -d --no-build
```

Open http://localhost:8501. The results are written to `NIH Extractor/data`, `NIH Extractor/outputs`, and `NIH Extractor/digests`.

Compose starts the dashboard again after Docker or the computer restarts. The quick start container does not.

To build the image from the source in the clone, run `docker compose up --build -d`. To stop the dashboard, run `docker compose down`.

On Linux, if your user ID is not 1000, start it as yourself: `APP_UID=$(id -u) APP_GID=$(id -g) docker compose up -d --no-build`. To keep the two values, write them as `APP_UID=...` and `APP_GID=...` in a file named `.env` beside `compose.yaml`.

## Run the command-line tool

Run a command in the container that serves the dashboard:

```bash
docker exec nih-grant-matcher python -m nih_grant_matcher run --source nih-guide
```

Or run a command in a container of its own, which exits when the command ends:

```bash
docker run --rm \
  -v "$PWD/data:/app/data" -v "$PWD/outputs:/app/outputs" -v "$PWD/digests:/app/digests" \
  ghcr.io/jrmatherly/nih-grant-matcher:latest \
  python -m nih_grant_matcher excel
```

With Docker Compose, the container has a different name, so `docker exec nih-grant-matcher` does not find it. From the repository root, run a command in the container that serves the dashboard:

```bash
docker compose exec app python -m nih_grant_matcher run --source nih-guide
```

Or run a command in a container of its own: `docker compose run --rm app python -m nih_grant_matcher excel`.

| Command | Result |
| --- | --- |
| `run --source nih-guide` | Fetches, scores, and saves opportunities, then writes `digests/latest.md`. `--source` also accepts `grants.gov` and `both`. |
| `digest` | Writes the digest again from the saved opportunities. |
| `excel` | Writes the saved opportunities to `outputs/nih_grant_opportunities.xlsx`. |
| `reporter-context --term "machine learning"` | Prints related funded projects from NIH RePORTER. |
| `profile show` | Prints the saved profile, or the built-in one when none is saved. |
| `profile export --out data/profile.json` | Writes that profile to a file. Give a path under `data/`, so that the file lands in the mounted folder. A path outside the mounted folders fails with "Permission denied". |
| `profile import data/profile.json` | Saves the profile in the file, or refuses a file that is not a valid profile. |
| `profile reset` | Deletes the saved profile, so ranking uses the built-in one. |
| `apply start PAR-27-074 --type R03` | Starts an application for a saved opportunity and prints its number. Add `--resubmission` for a resubmission. |
| `apply list` | Lists the applications. |
| `apply fetch 1` | Fetches the full announcement of application 1. |
| `apply requirements 1` | Prints the standing rules and what the announcement adds. |
| `apply extract 1` | Asks the model you chose to read Sections I, IV and V of the fetched announcement and list what they ask for. Nothing counts until you confirm it in the dashboard. |
| `apply add 1 --kind aim --text "Map heart cells."` | Adds an input. `--file data/aim.txt` reads the text from a UTF-8 file. For `--kind reference`, add `--label smith2021`, and cite the reference in a section as `[@smith2021]`. |
| `apply write 1 project-narrative --file data/narrative.txt` | Saves the text of a UTF-8 file as the newest revision of the section. Put the file under `data/`, so that the container can read it. A file outside the mounted folders fails with "No such file or directory". |
| `apply verify 1` | Checks that each reference you listed with a PMID or a DOI exists, and prints what the index holds for it. It sends each PMID to NCBI (PubMed) and each DOI without a PMID to Crossref, and none of your text. It exits with 1 when a lookup fails. |
| `apply draft 1 project-narrative` | Asks the model to draft the section from your inputs, and prints the proposal with its number. Nothing changes until you accept it. When an input is missing, it names the input and exits with 1. |
| `apply polish 1 project-narrative` | Asks the model to polish the newest revision of the section, and prints the proposal with its number. |
| `apply revise 1 project-narrative --instruction "Shorten it."` | Asks the model to revise the newest revision as you instruct, and prints the proposal with its number. |
| `apply accept 1 4` | Makes proposal 4 the newest revision of its section. |
| `apply discard 1 6` | Sets proposal 6 aside. It stays in the log. |
| `apply review 1 project-narrative` | Asks the model to score the newest revision against NIH's review factors. The model sees only the section and the review criteria you confirmed, and each score is the model's estimate, not NIH's. |
| `apply check 1` | Prints each section with its state and its findings. It exits with 1 while an error stands. |
| `apply sign 1 project-narrative --signer "A. Applicant"` | Signs off the newest revision. |
| `apply disclosure 1 --off` | Leaves the AI-use statement out of the export. `--on` puts it back and prints it. |
| `apply export 1 --out outputs/application-1` | Writes the section files, the requirements, the provenance log, and the AI-use statement while it is on, to the folder. Give a path under `outputs/`, so that the files land in the mounted folder. A relative path outside the mounted folders fails with "Permission denied". An absolute path such as `/tmp/export` is written inside the container and is lost with it. |
| `apply delete 1 --yes` | Deletes the application and everything logged for it. Without `--yes`, nothing is deleted. |
| `models --provider claude` | Chooses the provider of the model that helps you write, prints the host that receives your text and where the key was found, and lists the provider's models. Add `--model NAME` to choose one of them. For a self-hosted server, use `--provider compatible --base-url http://host:port/v1`. |
| `models --consent` | Agrees to send your text to the chosen provider's host. None of your text is sent to a host before you agree. Listing the models contacts the provider, with your key when there is one. |

Add `--help` to a command to see its options. Do not run `rarity-table` in the container. It rewrites a file inside the image, and the container's user cannot write there.

## Give the container a key for a model

The Apply view can ask a model to help you write. Choose the provider, the model, and a self-hosted server's address in the dashboard's **Model** section, under **Settings** or in the Apply view, or with the `models` command. The container needs only the key, in one of these variables:

| Provider | Variable |
| --- | --- |
| `claude` | `ANTHROPIC_API_KEY`. A key that is not scoped to one workspace also needs the workspace's ID, which you set in the dashboard's **Model** section. |
| `openai` | `OPENAI_API_KEY` |
| `gemini` | `GEMINI_API_KEY` |
| `compatible` | `GRANT_MATCHER_LLM_KEY`, when the server needs a key. Ollama does not. |

The commands in this section have not yet been run against the image.

[Docker's documentation](https://docs.docker.com/compose/how-tos/use-secrets/) warns that a key in an environment variable can be exposed, for example in a log. Mount the key as a file instead, and give its path in the variable of the same name with `_FILE` added. With Docker Compose, save the key in `anthropic_api_key.txt` beside `compose.yaml`, and write a file named `compose.override.yaml` beside it:

```yaml
services:
  app:
    environment:
      ANTHROPIC_API_KEY_FILE: /run/secrets/anthropic_api_key
    secrets:
      - anthropic_api_key
secrets:
  anthropic_api_key:
    file: ./anthropic_api_key.txt
```

Compose reads the override file by itself, and mounts the key at `/run/secrets/anthropic_api_key`. On Linux, the container's user, 1000 or your `APP_UID`, must be able to read the file.

With `docker run`, mount the file and name it in the variable:

```bash
docker run -d --name nih-grant-matcher \
  -p 127.0.0.1:8501:8501 \
  -v "$PWD/data:/app/data" -v "$PWD/outputs:/app/outputs" -v "$PWD/digests:/app/digests" \
  -v "$PWD/anthropic_api_key.txt:/run/secrets/anthropic_api_key:ro" \
  -e ANTHROPIC_API_KEY_FILE=/run/secrets/anthropic_api_key \
  ghcr.io/jrmatherly/nih-grant-matcher:latest
```

`compose.yaml` also passes the eight variables on from your shell when they are set, so `ANTHROPIC_API_KEY=... docker compose up -d --no-build` works too. A variable wins over a file, and a file wins over a key saved in the dashboard. A key saved in the dashboard goes to `data/llm-keys.json`, which only the container's user can read.

## Where the results are saved

| Folder in the container | Contents |
| --- | --- |
| `/app/data` | `grants.sqlite3`, the database of saved opportunities, the profile, and the applications |
| `/app/outputs` | Excel files, and the applications you export |
| `/app/digests` | Markdown digests |

The `-v` options connect these folders to folders on your computer. Without them, the results are lost when the container is removed.

On Linux, the container writes as user 1000. If your user has a different ID, create the folders yourself and add `--user "$(id -u):$(id -g)"` after `docker run` in each command, so that the container writes as you:

```bash
mkdir -p data outputs digests
```

If the folders belong to someone else, give them to your user first. This is the case when Docker created them as root, and when they belong to user 1000 from a start without `--user`:

```bash
sudo chown -R "$(id -u):$(id -g)" data outputs digests
```

Docker Desktop on macOS and Windows does not need this step.

## Update, pin, stop, and remove

- **Update to the newest image.** Pull it, then replace the container:

  ```bash
  docker pull ghcr.io/jrmatherly/nih-grant-matcher:latest
  docker rm -f nih-grant-matcher
  ```

  Then run the `docker run` command from the quick start again. Your results stay in the folders.

  With Docker Compose, run these two commands from the repository root:

  ```bash
  docker compose pull
  docker compose up -d --no-build
  ```

- **Pin a version.** Every build has a tag of the form `sha-<commit>`, for example `sha-9697e50`. A release has a tag such as `1.2.0`. Use one in place of `latest` to stay on that build.
- **Stop and start.** `docker stop nih-grant-matcher` and `docker start nih-grant-matcher`.
- **Remove.** `docker rm -f nih-grant-matcher` removes the container. `docker rmi ghcr.io/jrmatherly/nih-grant-matcher:latest` removes the image.
- **Read the log.** `docker logs nih-grant-matcher`.
- **With Docker Compose.** `docker compose stop` and `docker compose start` stop and start the dashboard. `docker compose down` removes the container, and `docker compose logs app` shows the log.

Saved opportunities are scored again each time they are read, so an update that changes scoring shows at once. `latest` is normally rebuilt every week with Debian's security fixes. GitHub turns the weekly rebuild off after 60 days without activity in the repository. To turn it on again, open the repository's Actions tab, select the Docker image workflow, and select Enable workflow. A build with a serious vulnerability that has a fix is not published.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `port is already allocated` | Another program uses port 8501. | Change the first number: `-p 127.0.0.1:8502:8501`, then open http://localhost:8502. |
| `Conflict. The container name "/nih-grant-matcher" is already in use` | A container from an earlier start still exists. | `docker rm -f nih-grant-matcher`, then start again. |
| The page does not load in the first seconds | The dashboard is still starting. | Wait until `docker ps` shows `(healthy)`. This took 5 to 30 seconds in testing. |
| `Search failed` with a web address in the message | The named service did not answer after three attempts. | Check your internet connection and try again. |
| `unable to open database file`, `attempt to write a readonly database`, or `Permission denied` on Linux | The folders or the files in them belong to another user. | Run the `chown` command in "Where the results are saved", and start the container with the `--user` option shown there. |
| `no matching manifest` | The computer's processor is not `amd64` or `arm64`. | Build from source on that computer: `docker compose up --build -d`. |
