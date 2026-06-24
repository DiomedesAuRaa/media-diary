import csv
import os
import sys
from pathlib import Path

from google import genai

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = REPO_ROOT / "data" / "movies.csv"


def load_env() -> None:
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()

if not os.environ.get("GEMINI_API_KEY"):
    raise ValueError("Error: GEMINI_API_KEY not found in your .env file.")

client = genai.Client()


def parse_movie_diary(file_path: Path):
    liked_movies = []
    all_seen_movies = []

    with file_path.open(mode="r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)

        for row in reader:
            title = row.get("Movie")
            rating_str = row.get("Rating", "0")
            director = row.get("Director", "Unknown Director")

            if not title:
                continue

            all_seen_movies.append(title.strip())

            try:
                rating = float(rating_str)
            except (ValueError, TypeError):
                continue

            if rating >= 8.0:
                liked_movies.append(f"- {title} ({director})")

    return "\n".join(liked_movies), ", ".join(all_seen_movies)


def generate_recommendations(liked_str: str, seen_str: str):
    prompt = f"""
    You are an expert film recommendation engine.

    Here is a list of movies I have rated highly (8/10 or above):
    {liked_str}

    CRITICAL CONSTRAINT: Here is a list of ALL movies I have already watched. You are STRICTLY FORBIDDEN from recommending any movie on this list, regardless of its rating:
    {seen_str}

    Based on my taste profile, provide exactly 5 tailored movie recommendations that I HAVE NOT WATCHED YET.

    Output ONLY a clean, bulleted list. Do not include any introductory greetings, concluding remarks, or markdown headers.

    Format each item EXACTLY like this example, keeping the description to a strict 1 or 2 sentence maximum with a blank line between bullets:

    * **Movie Title (Year)** - Directed by [Director]. [1 to 2 sentences MAX explaining the connection to my taste and why it is worth watching.]

    * **Next Movie Title (Year)** - Directed by [Director]. [Description here.]
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    return response.text


if __name__ == "__main__":
    if not CSV_PATH.exists():
        print(f"Error: Could not find '{CSV_PATH}'.")
        sys.exit(1)

    print("Parsing your movie library and building blocklist...")
    liked_profile, seen_blocklist = parse_movie_diary(CSV_PATH)

    if not liked_profile:
        print("Warning: No movies matched the rating criteria (>= 8.0). Check your headers.")
    else:
        print("Generating fresh recommendations...\n")
        results = generate_recommendations(liked_profile, seen_blocklist)

        print("=== YOUR PERSONALIZED FILM RECOMMENDATIONS ===\n")

        cleaned_lines = [line.strip() for line in results.strip().split("\n") if line.strip()]
        print("\n\n".join(cleaned_lines))
        print()
