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

3. Open http://localhost:8501.

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

With Docker Compose, the same command is `docker compose run --rm app python -m nih_grant_matcher excel`.

| Command | Result |
| --- | --- |
| `run --source nih-guide` | Fetches, scores, and saves opportunities, then writes `digests/latest.md`. `--source` also accepts `grants.gov` and `both`. |
| `digest` | Writes the digest again from the saved opportunities. |
| `excel` | Writes the saved opportunities to `outputs/nih_grant_opportunities.xlsx`. |
| `reporter-context --term "machine learning"` | Prints related funded projects from NIH RePORTER. |

Add `--help` to a command to see its options. Do not run `rarity-table` in the container. It rewrites a file inside the image, and the container's user cannot write there.

## Where the results are saved

| Folder in the container | Contents |
| --- | --- |
| `/app/data` | `grants.sqlite3`, the database of saved opportunities |
| `/app/outputs` | Excel files |
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

- **Pin a version.** Every build has a tag of the form `sha-<commit>`, for example `sha-662dc90`. A release has a tag such as `1.2.0`. Use one in place of `latest` to stay on that build.
- **Stop and start.** `docker stop nih-grant-matcher` and `docker start nih-grant-matcher`.
- **Remove.** `docker rm -f nih-grant-matcher` removes the container. `docker rmi ghcr.io/jrmatherly/nih-grant-matcher:latest` removes the image.
- **Read the log.** `docker logs nih-grant-matcher`.

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
