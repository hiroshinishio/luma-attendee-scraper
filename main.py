#!/usr/bin/env python3
# flake8: noqa: E501
# pylint: disable=line-too-long
"""
How to run:
1. Install dependencies: pip install -r requirements.txt
2. Install playwright browsers: playwright install
3. Run the script: python main.py "https://lu.ma/your-event-url"

Example event URL: https://lu.ma/ai-for-developers-22?tk=SzndEF
The script will save a CSV file with participant data in your Downloads folder.
"""

import csv
import os
import argparse
from functools import wraps
from pathlib import Path
from typing import Callable, Any, TypeVar
from playwright.sync_api import sync_playwright

# Define a generic type variable for the function return type
T = TypeVar("T")


def handle_exceptions(func: Callable[..., T]) -> Callable[..., T | None]:
    @wraps(func)
    def wrapper(*func_args: Any, **func_kwargs: Any) -> T | None:
        try:
            return func(*func_args, **func_kwargs)
        except Exception as e:  # pylint: disable=broad-except
            print(f"An error occurred: {str(e)}")
            return None

    return wrapper


@handle_exceptions
def scrape_luma_event(url: str):
    """
    Scrape Luma event participants and save LinkedIn URLs to CSV

    Args:
        url (str): The full URL of the Luma event like https://lu.ma/4uzoqc46?tk=YJBZOR
    """
    downloads_path = str(Path.home() / "Downloads")
    session_path = f"{downloads_path}/luma-auth.json"
    session_path = session_path if os.path.exists(session_path) else None

    # with is a context manager that will automatically close the browser when the block is exited
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=session_path)
        page = context.new_page()

        # Navigate directly to the login page first if we don't have a session
        if not session_path:
            print("No session found, logging in")

            login_url = f"https://lu.ma/signin?next={url.split('lu.ma/')[1]}"
            page.goto(login_url)
            page.wait_for_load_state("networkidle")
            print("\nLogin page loaded")

            # Handle login
            email = "wes@gitauto.ai"
            page.fill('input[type="email"]', email)
            page.click('button:has-text("Continue with Email")')

            # Wait for the "Enter Code" heading to appear
            page.wait_for_selector('h1:has-text("Enter Code")')
            print("\nCheck your email for the verification code")
            verification_code = input("Enter the 6-digit verification code: ")

            # Fill in verification code
            for i, digit in enumerate(verification_code):
                page.fill(f"#code-input-{i}", digit)

            # Wait for login to complete and redirect
            # Wait for the avatar element to appear, which indicates successful login
            page.wait_for_selector(".avatar-wrapper.flex-center", timeout=30000)
            print("Login successful")

            # Keep the sign in session
            context.storage_state(path=f"{downloads_path}/luma-auth.json")

        # After login, we might be redirected to home page, so navigate to event URL explicitly
        page.wait_for_timeout(5000)
        print("Signed in, navigating to event page")
        page.goto(url)

        # Wait for event page to load
        page.wait_for_load_state("networkidle")
        print("Navigated to event page")

        # Get event title, date, time, and place
        event_title = page.locator("h1.title").inner_text()
        event_date = page.locator(".icon-row .title").first.inner_text()
        event_time = page.locator(".icon-row .desc").first.inner_text()
        print(f"Event Title: {event_title}")
        print(f"Event Date: {event_date}")
        print(f"Event Time: {event_time}")

        # Get event place - check if it's a link (IRL) or just text (Virtual)
        place_container = page.locator(".meta.flex-column > a.row-container")
        if place_container.count() > 0:
            # IRL event
            event_place = (
                f"{place_container.locator('.title.text-ellipses').inner_text()}, "
                f"{place_container.locator('.desc.text-ellipses').inner_text()}"
            )
        else:
            # Virtual event
            place_container = page.locator(".meta.flex-column > div.row-container")
            event_place = place_container.locator(".title.text-ellipses").inner_text()
        print(f"Event Place: {event_place}")

        # Get event host
        host_element = page.locator('div:has-text("Presented by") + a.title')
        event_host = host_element.locator(".fw-medium").inner_text()
        print(f"Event Host: {event_host}")

        # Click the guests button
        # Look for button containing text pattern like "Name1, Name2 and X others"
        guests_button = (
            page.get_by_role("button").filter(has_text="and").filter(has_text="others")
        )
        guests_button.wait_for(state="visible")
        guests_button.click()
        print("Guests button clicked")

        # Wait for modal to appear
        page.wait_for_selector(".lux-modal-body")
        modal = page.locator(".lux-modal-body")
        print("Modal body was found")
        page.wait_for_timeout(3000)

        modal_content = modal.locator("div.flex-column.outer.overflow-auto")
        print(
            f"Modal content HTML: {modal_content.evaluate('el => el.cloneNode(false).outerHTML')}"
        )
        current_participant_count = 0
        last_participant_count = 0
        max_attempts = 3
        attempts = 0

        while attempts < max_attempts:
            # Get current number of participants
            current_participants = modal_content.locator(
                '.flex-center.gap-2.spread a[href^="/user/usr-"]'
            )
            current_participant_count = current_participants.count()
            print(f"Current participant count: {current_participant_count}")

            # Scroll to bottom of modal content
            modal_content.focus()
            modal_content.press("End")

            # Wait for 5 seconds to load new participants
            page.wait_for_timeout(5000)

            # Check if we've loaded new participants
            print(f"Last participant count: {last_participant_count}")
            if current_participant_count == last_participant_count:
                attempts += 1
            else:
                attempts = 0

            last_participant_count = current_participant_count

        print(f"Total participants loaded: {current_participant_count}")

        # Get all participant elements and store necessary information first
        participants: list[dict[str, str]] = []
        participant_elements = modal_content.locator(
            '.flex-center.gap-2.spread a[href^="/user/usr-"]'
        ).all()

        # First collect all names and profile URLs
        for element in participant_elements:
            full_name = element.locator(".name.text-ellipses").inner_text()

            # Skip if the name looks like an email
            if "@" in full_name:
                print(f"Skipping email-like name: {full_name}")
                continue

            # Split name into first and last name
            name_parts = full_name.split(maxsplit=1)
            first_name = name_parts[0].capitalize()
            last_name = name_parts[1].capitalize() if len(name_parts) > 1 else ""

            profile_url = element.get_attribute("href")
            if not profile_url:
                print(f"No profile URL found for {full_name}, skipping")
                continue

            full_profile_url = f"https://lu.ma{profile_url}"
            participants.append(
                {
                    "first_name": first_name,
                    "last_name": last_name,
                    "profile_url": full_profile_url,
                }
            )

        # Then visit each profile URL separately
        for participant in participants:
            print(f"Processing: {participant['first_name']} {participant['last_name']}")
            page.goto(participant["profile_url"])
            page.wait_for_load_state("networkidle")

            linkedin_link = page.locator('.social-links a[href*="linkedin.com"]').first

            if linkedin_link.count() == 0:
                print(
                    f"No LinkedIn link found for {participant['first_name']} {participant['last_name']}, skipping"
                )
                continue

            linkedin_url = linkedin_link.get_attribute("href")
            if not linkedin_url:
                print(
                    f"No LinkedIn URL found for {participant['first_name']} {participant['last_name']}, skipping"
                )
                continue

            participant["linkedin"] = linkedin_url
            print(f"LinkedIn: {linkedin_url}")

        # Filter out participants without LinkedIn URLs
        print(f"Participants length: {len(participants)}")
        participants = [p for p in participants if "linkedin" in p]
        print(f"Participants length after filtering: {len(participants)}")

        # Save to CSV in Downloads folder
        print(f"\nSaving to CSV in {downloads_path}")
        csv_path = os.path.join(downloads_path, "luma_participants.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=[
                    "first_name",
                    "last_name",
                    "linkedin",
                    "custom_att_1",  # event_title
                    "custom_att_2",  # event_date
                    "custom_att_3",  # event_time
                    "custom_att_4",  # event_place
                    "custom_att_5",  # event_host
                    "custom_att_6",  # event_source
                ],
            )
            writer.writeheader()

            # Update each participant with the same event details
            for participant in participants:
                participant_data = {
                    "first_name": participant["first_name"],
                    "last_name": participant["last_name"],
                    "linkedin": participant["linkedin"],
                    "custom_att_1": event_title,
                    "custom_att_2": event_date,
                    "custom_att_3": event_time,
                    "custom_att_4": event_place,
                    "custom_att_5": event_host,
                    "custom_att_6": "Luma",
                }
                writer.writerow(participant_data)

        print(f"CSV file saved to: {csv_path}")

        # Close the browser
        browser.close()


if __name__ == "__main__":
    # Set up argument parser
    DESCRIPTION = "Scrape Luma event participants and their LinkedIn URLs"
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    HELP = "The full URL of the Luma event (e.g., https://lu.ma/4uzoqc46?tk=YJBZOR or https://lu.ma/ai-for-developers-22?tk=SzndEF)"
    parser.add_argument("url", type=str, help=HELP)

    # Parse arguments
    args = parser.parse_args()

    # Run scraper with provided URL
    scrape_luma_event(args.url)
