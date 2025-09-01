### To run your local Django development server, use this command from your project root: python manage.py runserver

### To make migrations after any code changes (first save the changes) run these two lines of code:
###     python manage.py makemigrations voting_record
###     python manage.py migrate

""" trying to scrape the individual MP vote details, then move on to the MP comparison, then front end"""

from bs4 import BeautifulSoup
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import random
import os
import django
import pandas as pd
import requests
import re

# Set the Django settings module (replace 'myproject' with your actual project name)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'democrasee.settings')

# Initialize Django
django.setup()

# Import updated models
from core.models import (
    Parliament, VoteRecord, MPVote, MemberOfParliament, Bill,
    Committee, CommitteeMember, PolicyTopic
)


def get_or_create_parliament(parliament_number=45):
    """Get or create a Parliament record"""
    parliament, created = Parliament.objects.get_or_create(
        number=parliament_number,
        defaults={
            'start_date': datetime(2025, 5, 26).date(),  # 45th Parliament start
            'is_current': True
        }
    )
    return parliament


def clean_mp_name_fixed(name):
    """Clean MP names by removing constituency and title information"""
    if not name:
        return None
    # Remove constituency info in parentheses
    name = re.sub(r'\([^)]*\)', '', name)
    # Remove "Hon." and "The Right Hon." prefixes
    name = re.sub(r'^(The\s+)?(Right\s+)?Hon\.?\s*', '', name, flags=re.IGNORECASE)
    # Normalize whitespace
    name = re.sub(r'\s+', ' ', name.strip())
    return name.strip()


def find_mp_with_complete_name_matching(mp_name):
    """Complete MP matching that handles all name variations"""
    # Try exact match first
    mp = MemberOfParliament.objects.filter(name=mp_name).first()
    if mp:
        return mp
    # Manual mappings for known cases
    known_mappings = {
        'Amanpreet Gill': 'Amanpreet S. Gill',
        'Damien Kurek': 'Damien C. Kurek',
        'David Mcguinty': 'David J. Mcguinty',
        'Emma Harrison': 'Emma Harrison Hill',
        'Michael Chong': 'Michael D. Chong',
        'Robert Morrissey': 'Robert J. Morrissey',
        'Vincent Ho': 'Vincent Neil Ho'
    }
    if mp_name in known_mappings:
        mapped_name = known_mappings[mp_name]
        return MemberOfParliament.objects.filter(name=mapped_name).first()
    # Fallback: intelligent matching for any other cases
    parts = mp_name.strip().split()
    if len(parts) >= 2:
        first_name = parts[0]
        last_name = parts[-1]
        potential_matches = MemberOfParliament.objects.filter(
            name__istartswith=first_name + ' '
        ).filter(
            name__iendswith=' ' + last_name
        )
        if potential_matches.count() == 1:
            return potential_matches.first()
    return None


def map_party_code(political_affiliation):
    """Map full party names to standardized codes"""
    party_mapping = {
        'conservative': 'CPC',
        'liberal': 'LPC',
        'new democratic party': 'NDP',
        'bloc québécois': 'BQ',
        'green party': 'GP',
        'people\'s party': 'PPC',
        'independent': 'IND',
    }

    affiliation_lower = political_affiliation.lower()
    for key, code in party_mapping.items():
        if key in affiliation_lower:
            return code
    return 'OTHER'


def scrape_members_of_parliament_details(offline=False):
    """Scrape MP details with enhanced data mapping"""
    url = "https://www.ourcommons.ca/members/en/search?parliament=all&caucusId=all&province=all&gender=all"
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')

    mp_honourific_title = [tag.text.strip() for tag in soup.find_all(attrs={'class': 'ce-mip-mp-honourable'})]
    mp_name = [tag.text.strip() for tag in soup.find_all(attrs={'class': 'ce-mip-mp-name'})]
    mp_political_affiliation = [tag.text.strip() for tag in soup.find_all(attrs={'class': 'ce-mip-mp-party'})]
    mp_riding = [tag.text.strip() for tag in soup.find_all(attrs={'class': 'ce-mip-mp-constituency'})]
    mp_province = [tag.text.strip() for tag in soup.find_all(attrs={'class': 'ce-mip-mp-province'})]

    mp_statuses = []
    mp_tiles = soup.find_all("div", class_="ce-mip-mp-tile-container")
    for tile in mp_tiles:
        tooltip = tile.find("div", class_="ce-mip-mp-tooltip-former")
        status_tag = tooltip.find("span", class_="sr-only") if tooltip else None
        status = status_tag.text.strip() if status_tag else "Active Member of Parliament"
        mp_statuses.append(status)

    mp_list = []

    for i in range(len(mp_name)):
        cleaned_name = clean_mp_name_fixed(mp_name[i])
        honourific = mp_honourific_title[i] if i < len(mp_honourific_title) else ''
        political_affiliation = mp_political_affiliation[i]
        party_code = map_party_code(political_affiliation)

        # Map status to standardized choices
        status_mapped = 'ACTIVE' if 'active' in mp_statuses[i].lower() else 'FORMER'

        mp_list.append({
            "Honourific Title": honourific,
            "MP Name": cleaned_name,
            "Constituency": mp_riding[i],
            "Political Affiliation": political_affiliation,
            "Party Code": party_code,
            "Province": mp_province[i],
            "Status": status_mapped
        })

        if not offline:
            MemberOfParliament.objects.update_or_create(
                name=cleaned_name,
                defaults={
                    "honourific_title": honourific,
                    "political_affiliation": political_affiliation,
                    "party_code": party_code,
                    "constituency": mp_riding[i],
                    "province": mp_province[i],
                    "status": status_mapped,
                }
            )

    if offline:
        return pd.DataFrame(mp_list)
    else:
        return f" Scraped {len(mp_name)} MP records successfully!"


def scrape_all_parliament_votes(start_parliament=38, end_parliament=45, offline=False):
    """
    Scrape votes from multiple parliaments and sessions.
    Default range: 38th to 45th Parliament
    """
    all_votes_data = []

    # Parliament-session combinations based on your screenshot
    parliament_sessions = [
        (45, 1),  # 45th Parliament, 1st Session (current)
        (44, 1),  # 44th Parliament, 1st Session
        (43, 2),  # 43rd Parliament, 2nd Session
        (43, 1),  # 43rd Parliament, 1st Session
        (42, 1),  # 42nd Parliament, 1st Session
        (41, 2),  # 41st Parliament, 2nd Session
        (41, 1),  # 41st Parliament, 1st Session
        (40, 3),  # 40th Parliament, 3rd Session
        (40, 2),  # 40th Parliament, 2nd Session
        (40, 1),  # 40th Parliament, 1st Session
        (39, 2),  # 39th Parliament, 2nd Session
        (39, 1),  # 39th Parliament, 1st Session
        (38, 1),  # 38th Parliament, 1st Session
    ]

    for parl_num, session_num in parliament_sessions:
        print(f"\nScraping {parl_num}th Parliament, Session {session_num}...")

        # Construct URL for specific parliament and session
        url = f"https://www.ourcommons.ca/members/en/votes?parlSession={parl_num}-{session_num}"

        try:
            webpage_response = requests.get(url)
            soup = BeautifulSoup(webpage_response.content, 'html.parser')

            # Get or create parliament record
            parliament, created = Parliament.objects.get_or_create(
                number=parl_num,
                defaults={
                    'start_date': datetime(2000 + parl_num - 38, 1, 1).date(),  # Placeholder dates
                    'is_current': (parl_num == 45)
                }
            )

            # Find votes using the same logic as before
            a_tags = soup.find_all(attrs={'class': 'ce-mip-table-number'})

            if not a_tags:
                print(f"  No votes found for {parl_num}th Parliament, Session {session_num}")
                continue

            vote_numbers = [a.text.strip().replace("No. ", "") for a in a_tags]
            td_elements = soup.find_all('td')

            # Skip if not enough TD elements
            if len(td_elements) < 6:
                print(f"  Not enough data elements found")
                continue

            subjects = [td_elements[i].text.strip() for i in range(2, len(td_elements) - 3, 6)]
            vote_data = [td_elements[i].text.strip() for i in range(3, len(td_elements) - 2, 6)]
            vote_results = [td_elements[i].text.strip() for i in range(4, len(td_elements) - 1, 6)]
            vote_dates = [td_elements[i].text.strip() for i in range(5, len(td_elements), 6)]

            votes_in_session = 0

            for i in range(len(vote_numbers)):
                try:
                    vote_number = int(vote_numbers[i])
                    subject = subjects[i] if i < len(subjects) else "Unknown"
                    vote_data_value = vote_data[i] if i < len(vote_data) else "Unknown"

                    # Map vote results
                    vote_result_mapped = 'AGREED' if 'agreed' in vote_results[i].lower() else 'NEGATIVED'

                    # Parse date
                    try:
                        vote_date = datetime.strptime(vote_dates[i], "%A, %B %d, %Y").date()
                    except ValueError:
                        print(f"    Warning: Could not parse date '{vote_dates[i]}' for vote {vote_number}")
                        continue

                    vote_dict = {
                        "Parliament": parl_num,
                        "Session": session_num,
                        "Vote Number": vote_number,
                        "Subject": subject,
                        "Vote Data": vote_data_value,
                        "Vote Result": vote_result_mapped,
                        "Vote Date": vote_date
                    }

                    all_votes_data.append(vote_dict)
                    votes_in_session += 1

                    if not offline:
                        VoteRecord.objects.get_or_create(
                            vote_number=vote_number,
                            parliament=parliament,
                            session=session_num,
                            defaults={
                                "subject": subject,
                                "vote_result": vote_result_mapped,
                                "vote_date": vote_date,
                            }
                        )

                except Exception as e:
                    print(f"    Error processing vote {i}: {e}")
                    continue

            print(
                f"  Successfully scraped {votes_in_session} votes from {parl_num}th Parliament, Session {session_num}")

            # Add a small delay between requests to be respectful
            time.sleep(1)

        except Exception as e:
            print(f"  Error scraping {parl_num}th Parliament, Session {session_num}: {e}")
            continue

    print(f"\nTotal votes scraped across all parliaments: {len(all_votes_data)}")

    if offline:
        return pd.DataFrame(all_votes_data)
    else:
        return f"Scraped {len(all_votes_data)} voting records across multiple parliaments!"


def scrape_mp_vote_details_table_based(parliament_sessions=None, start_vote=1, offline=False):
    """
    Table-based MP vote scraping that works with the actual Parliament website structure

    Args:
        parliament_sessions: List of (parliament, session) tuples
        start_vote: Vote number to start from
        offline: If True, returns DataFrame instead of saving to DB
    """

    if parliament_sessions is None:
        discovered_sessions = VoteRecord.objects.values(
            'parliament__number', 'session'
        ).distinct().order_by('-parliament__number', '-session')

        parliament_sessions = [
            (session['parliament__number'], session['session'])
            for session in discovered_sessions
            if session['parliament__number'] is not None
        ]

        if not parliament_sessions:
            return "No parliament sessions found."

    total_votes_processed = 0
    total_mp_votes_created = 0
    all_mp_votes_data = []

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })

    for parliament_number, session_number in parliament_sessions:
        print(f"\nProcessing Parliament {parliament_number}, Session {session_number}")

        votes = VoteRecord.objects.filter(
            parliament__number=parliament_number,
            session=session_number,
            vote_number__gte=start_vote
        ).order_by('vote_number')

        if not votes.exists():
            continue

        print(f"Found {votes.count()} votes to process")
        parliament_mp_votes = 0

        for vote_record in votes:
            vote_number = vote_record.vote_number
            url = f"https://www.ourcommons.ca/members/en/votes/{parliament_number}/{session_number}/{vote_number}?view=member"

            print(f"  Vote {vote_number}...", end=" ")

            try:
                response = session.get(url, timeout=30)
                if response.status_code != 200:
                    print(f"Failed (HTTP {response.status_code})")
                    continue

                soup = BeautifulSoup(response.content, 'html.parser')
                mp_votes = {}

                # STRATEGY 1: Look for data tables containing MP vote information
                tables = soup.find_all('table')

                for table in tables:
                    rows = table.find_all('tr')

                    # Look for table rows that contain MP data
                    for row in rows:
                        cells = row.find_all(['td', 'th'])

                        # Skip header rows and rows without enough cells
                        if len(cells) < 2:
                            continue

                        # Look for MP link in the first cell
                        mp_link = None
                        for cell in cells[:2]:  # Check first two cells
                            link = cell.find('a', href=lambda x: x and '/members/en/' in x if x else False)
                            if link:
                                mp_link = link
                                break

                        if mp_link:
                            mp_name = clean_mp_name_fixed(mp_link.get_text(strip=True))
                            if mp_name and len(mp_name) > 3:
                                # Look for vote indication in the row
                                row_text = row.get_text().lower()

                                # Check each cell for vote indicators
                                vote_found = False
                                for cell in cells:
                                    cell_text = cell.get_text(strip=True).upper()

                                    # Direct vote indicators
                                    if cell_text in ['YEA', 'AGREED', 'FOR']:
                                        mp_votes[mp_name] = 'YEA'
                                        vote_found = True
                                        break
                                    elif cell_text in ['NAY', 'NEGATIVED', 'AGAINST']:
                                        mp_votes[mp_name] = 'NAY'
                                        vote_found = True
                                        break
                                    elif cell_text in ['PAIRED']:
                                        mp_votes[mp_name] = 'PAIRED'
                                        vote_found = True
                                        break

                                    # Check for icons or symbols that might indicate votes
                                    # Look for checkmarks, X marks, or other symbols
                                    if cell.find('i') or cell.find('span', class_=True):
                                        # Check if cell contains vote-indicating classes or icons
                                        icons = cell.find_all(['i', 'span'])
                                        for icon in icons:
                                            classes = icon.get('class', [])
                                            if any('check' in str(cls).lower() or 'yes' in str(
                                                    cls).lower() or 'agree' in str(cls).lower() for cls in classes):
                                                mp_votes[mp_name] = 'YEA'
                                                vote_found = True
                                                break
                                            elif any(
                                                    'x' in str(cls).lower() or 'no' in str(cls).lower() or 'nay' in str(
                                                            cls).lower() for cls in classes):
                                                mp_votes[mp_name] = 'NAY'
                                                vote_found = True
                                                break
                                        if vote_found:
                                            break

                                # If no explicit vote found, but MP is in table, might need different approach
                                if not vote_found and mp_name not in mp_votes:
                                    # Check if this table section has a heading that indicates vote type
                                    table_container = table.parent
                                    if table_container:
                                        container_text = table_container.get_text().lower()

                                        # Look at preceding headings
                                        prev_elements = []
                                        current = table
                                        for _ in range(5):  # Look at 5 preceding elements
                                            prev = current.find_previous_sibling()
                                            if prev:
                                                prev_elements.append(prev)
                                                current = prev
                                            else:
                                                break

                                        section_type = None
                                        for elem in prev_elements:
                                            elem_text = elem.get_text().lower()
                                            if 'yea' in elem_text or 'agreed' in elem_text:
                                                section_type = 'YEA'
                                                break
                                            elif 'nay' in elem_text or 'negatived' in elem_text:
                                                section_type = 'NAY'
                                                break
                                            elif 'paired' in elem_text:
                                                section_type = 'PAIRED'
                                                break

                                        if section_type:
                                            mp_votes[mp_name] = section_type

                # STRATEGY 2: Look for grouped sections with headings
                if not mp_votes:
                    # Find all h2, h3, h4 headings that might indicate vote sections
                    headings = soup.find_all(['h2', 'h3', 'h4', 'h5', 'h6'])

                    for heading in headings:
                        heading_text = heading.get_text().lower()

                        vote_type = None
                        if 'yea' in heading_text or 'agreed' in heading_text:
                            vote_type = 'YEA'
                        elif 'nay' in heading_text or 'negatived' in heading_text:
                            vote_type = 'NAY'
                        elif 'paired' in heading_text:
                            vote_type = 'PAIRED'

                        if vote_type:
                            # Look for MP links in the next few siblings
                            current = heading
                            for _ in range(5):  # Check next 5 siblings
                                next_elem = current.find_next_sibling()
                                if next_elem:
                                    mp_links = next_elem.find_all('a', href=lambda
                                        x: x and '/members/en/' in x if x else False)
                                    for link in mp_links:
                                        mp_name = clean_mp_name_fixed(link.get_text(strip=True))
                                        if mp_name and len(mp_name) > 3 and mp_name not in mp_votes:
                                            mp_votes[mp_name] = vote_type
                                    current = next_elem
                                else:
                                    break

                # STRATEGY 3: Look for div sections that might group MPs by vote type
                if not mp_votes:
                    divs = soup.find_all('div')

                    for div in divs:
                        div_text = div.get_text().lower()
                        mp_links_in_div = div.find_all('a', href=lambda x: x and '/members/en/' in x if x else False)

                        if mp_links_in_div and len(mp_links_in_div) > 5:  # Only consider divs with substantial MP lists
                            vote_type = None

                            # Check if this div or nearby elements indicate vote type
                            if 'yea' in div_text and 'nay' not in div_text:
                                vote_type = 'YEA'
                            elif 'nay' in div_text and 'yea' not in div_text:
                                vote_type = 'NAY'
                            elif 'paired' in div_text:
                                vote_type = 'PAIRED'

                            # Also check preceding sibling elements for context
                            if not vote_type:
                                prev_sibling = div.find_previous_sibling()
                                if prev_sibling:
                                    prev_text = prev_sibling.get_text().lower()
                                    if 'yea' in prev_text:
                                        vote_type = 'YEA'
                                    elif 'nay' in prev_text:
                                        vote_type = 'NAY'
                                    elif 'paired' in prev_text:
                                        vote_type = 'PAIRED'

                            if vote_type:
                                for link in mp_links_in_div:
                                    mp_name = clean_mp_name_fixed(link.get_text(strip=True))
                                    if mp_name and len(mp_name) > 3 and mp_name not in mp_votes:
                                        mp_votes[mp_name] = vote_type

                # Validate results
                vote_breakdown = {}
                for vote in mp_votes.values():
                    vote_breakdown[vote] = vote_breakdown.get(vote, 0) + 1

                real_votes = sum(count for vote_type, count in vote_breakdown.items()
                                 if vote_type in ['YEA', 'NAY', 'PAIRED'])

                if real_votes == 0:
                    print("No votes found")
                    continue

                # Add absent MPs
                if not offline:
                    active_mps = MemberOfParliament.objects.filter(status='ACTIVE')
                    for mp in active_mps:
                        if mp.name not in mp_votes:
                            mp_votes[mp.name] = 'ABSENT'

                # Save to database
                vote_mp_count = 0
                for mp_name, vote_mapped in mp_votes.items():
                    mp_vote_data = {
                        "Parliament": parliament_number,
                        "Session": session_number,
                        "Vote Number": vote_number,
                        "MP Name": mp_name,
                        "Vote": vote_mapped,
                        "Subject": vote_record.subject,
                        "Vote Date": vote_record.vote_date
                    }
                    all_mp_votes_data.append(mp_vote_data)

                    if not offline:
                        mp = find_mp_with_complete_name_matching(mp_name)
                        if mp:
                            try:
                                MPVote.objects.create(
                                    vote_record=vote_record,
                                    mp=mp,
                                    vote=vote_mapped,
                                    parliament=vote_record.parliament,
                                    session=session_number
                                )
                                vote_mp_count += 1
                                parliament_mp_votes += 1
                                total_mp_votes_created += 1
                            except Exception as e:
                                pass  # Skip errors for now

                # Update vote counts
                if not offline:
                    vote_record.update_vote_counts()

                print(f"✓ ({vote_breakdown})")
                total_votes_processed += 1
                time.sleep(random.uniform(0.5, 1.5))

            except Exception as e:
                print(f"Error: {e}")
                continue

        print(f"Parliament {parliament_number} complete: {parliament_mp_votes} MP votes created")

    print(f"\nSCRAPING COMPLETE!")
    print(f"Total votes processed: {total_votes_processed}")
    print(f"Total MP votes created: {total_mp_votes_created}")

    if offline:
        return pd.DataFrame(all_mp_votes_data)
    else:
        return f"Successfully scraped {total_mp_votes_created} MP votes from {total_votes_processed} votes"


def parse_session_date(date_string):
    """Parse session date strings and return the start date in YYYY-MM-DD format"""
    if not date_string or date_string == "N/A":
        return None

    try:
        if " to " in date_string:
            start_date_str = date_string.split(" to ")[0].strip()
        else:
            start_date_str = date_string.strip()

        parsed_date = datetime.strptime(start_date_str, "%B %d, %Y")
        return parsed_date.strftime("%Y-%m-%d")

    except ValueError:
        print(f"    Warning: Could not parse date '{date_string}', skipping...")
        return None


def scrape_bills(offline=False, delay_range=(1, 3), max_retries=3):
    """Scrapes bill details with enhanced data mapping"""
    base_url = "https://www.parl.ca/legisinfo/en/bills?parlsession=all&view=list"
    page = 1
    bills_data = []
    consecutive_failures = 0
    max_consecutive_failures = 5
    consecutive_empty_pages = 0
    max_consecutive_empty_pages = 5

    created_count = 0
    updated_count = 0
    error_count = 0

    # Setup session with retry strategy
    session = requests.Session()
    retry_strategy = Retry(
        total=max_retries,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    })

    while True:
        page_url = f"{base_url}&page={page}"
        print(f"Scraping page {page}: {page_url}")

        page_created = 0
        page_updated = 0

        try:
            if page > 1:
                delay = random.uniform(delay_range[0], delay_range[1])
                print(f"  Waiting {delay:.1f} seconds...")
                time.sleep(delay)

            response = session.get(page_url, timeout=30)

            if response.status_code != 200:
                print(f"  Failed to fetch page {page}. Status code: {response.status_code}")
                consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    print(f"  Too many consecutive failures ({consecutive_failures}). Stopping.")
                    break
                continue

            consecutive_failures = 0
            soup = BeautifulSoup(response.content, 'html.parser')

            bill_numbers = [bill.text.strip() for bill in soup.find_all('h4', class_="sr-only")]

            if not bill_numbers:
                potential_bills = soup.find_all('a', href=lambda x: x and '/bill/' in x if x else False)
                bill_numbers = [bill.text.strip() for bill in potential_bills if bill.text.strip()]

            if not bill_numbers:
                print(f"  No bills found on page {page}.")
                consecutive_empty_pages += 1

                if "No results found" in response.text or "no bills" in response.text.lower():
                    print("  Reached end of results.")
                    break
                elif consecutive_empty_pages >= max_consecutive_empty_pages:
                    print(f"  Found {consecutive_empty_pages} consecutive empty pages. Assuming end of data.")
                    break
                else:
                    print(f"  Empty page {consecutive_empty_pages}/{max_consecutive_empty_pages}. Trying next page...")
                    page += 1
                    continue

            consecutive_empty_pages = 0
            print(f"  Found {len(bill_numbers)} bills on page {page}")

            # Extract other data
            bill_subjects = []
            parliament_numbers = []
            session_dates = []

            h5_elements = soup.find_all('h5')
            bill_subjects = [h5.text.strip() for h5 in h5_elements[:len(bill_numbers)]]
            while len(bill_subjects) < len(bill_numbers):
                bill_subjects.append("N/A")

            parliament_elements = soup.find_all('div', class_="parliament-session")
            parliament_numbers = [p.text.strip() for p in parliament_elements[:len(bill_numbers)]]
            while len(parliament_numbers) < len(bill_numbers):
                parliament_numbers.append("N/A")

            date_elements = soup.find_all('div', class_="session-date-range")
            session_dates = [d.text.strip() for d in date_elements[:len(bill_numbers)]]
            while len(session_dates) < len(bill_numbers):
                session_dates.append("N/A")

            bill_sections = soup.find_all('div', class_='row bill-attributes-section')

            for i in range(len(bill_numbers)):
                bill_type_value = "N/A"
                sponsor_value = "N/A"
                current_status_value = "N/A"
                latest_activity_value = "N/A"

                if i < len(bill_sections):
                    section = bill_sections[i]

                    bill_type = section.find('div', class_='label', string='Bill type')
                    if bill_type and bill_type.find_next_sibling('div'):
                        bill_type_value = bill_type.find_next_sibling('div').text.strip()

                    sponsor = section.find('div', class_='label', string='Sponsor')
                    if sponsor and sponsor.find_next_sibling('div'):
                        sponsor_value = sponsor.find_next_sibling('div').text.strip()

                    current_status = section.find('div', class_='label', string='Current status')
                    if current_status and current_status.find_next_sibling('div'):
                        current_status_value = current_status.find_next_sibling('div').text.strip()

                    latest_activity = section.find('div', class_='label', string='Latest activity')
                    if latest_activity and latest_activity.find_next_sibling('div'):
                        latest_activity_value = latest_activity.find_next_sibling('div').text.strip()

                parsed_session_date = parse_session_date(session_dates[i] if i < len(session_dates) else "N/A")

                # Extract parliament number and session from parliament_numbers[i]
                parliament_text = parliament_numbers[i] if i < len(parliament_numbers) else "N/A"
                parliament_num = None
                session_num = 1  # Default

                if parliament_text != "N/A":
                    import re
                    # Parse "44th Parliament, 1st Session" or similar
                    parl_match = re.search(r'(\d+)(?:st|nd|rd|th)\s+Parliament', parliament_text)
                    if parl_match:
                        parliament_num = int(parl_match.group(1))

                    # Extract session number
                    session_match = re.search(r'(\d+)(?:st|nd|rd|th)\s+Session', parliament_text)
                    if session_match:
                        session_num = int(session_match.group(1))

                bills_data.append({
                    "Bill Number": bill_numbers[i],
                    "Subject": bill_subjects[i] if i < len(bill_subjects) else "N/A",
                    "Parliament": parliament_text,
                    "Parliament Number": parliament_num,
                    "Session Number": session_num,
                    "Session Date": session_dates[i] if i < len(session_dates) else "N/A",
                    "Parsed Session Date": parsed_session_date,
                    "Bill Type": bill_type_value,
                    "Sponsor": sponsor_value,
                    "Current Status": current_status_value,
                    "Latest Activity": latest_activity_value
                })

                if not offline and parliament_num:
                    try:
                        # Get or create parliament for THIS SPECIFIC BILL
                        parliament, _ = Parliament.objects.get_or_create(
                            number=parliament_num,
                            defaults={
                                'start_date': parsed_session_date if parsed_session_date else datetime(
                                    1900 + parliament_num, 1, 1).date(),
                                'is_current': (parliament_num == 45)
                            }
                        )

                        # Map bill type to standardized choices
                        bill_type_mapped = None
                        if bill_type_value != "N/A":
                            if 'government' in bill_type_value.lower():
                                if 'senate' in bill_type_value.lower():
                                    bill_type_mapped = 'SENATE_GOVERNMENT'
                                else:
                                    bill_type_mapped = 'GOVERNMENT'
                            elif 'private member' in bill_type_value.lower():
                                if 'senate' in bill_type_value.lower():
                                    bill_type_mapped = 'SENATE_PRIVATE_MEMBER'
                                else:
                                    bill_type_mapped = 'PRIVATE_MEMBER'
                            elif 'private' in bill_type_value.lower():
                                bill_type_mapped = 'PRIVATE'

                        # Map current status to standardized choices
                        status_mapped = 'INTRODUCED'  # default
                        if current_status_value != "N/A":
                            status_lower = current_status_value.lower()
                            if 'first reading' in status_lower:
                                status_mapped = 'FIRST_READING'
                            elif 'second reading' in status_lower:
                                status_mapped = 'SECOND_READING'
                            elif 'committee' in status_lower:
                                status_mapped = 'COMMITTEE'
                            elif 'report stage' in status_lower:
                                status_mapped = 'REPORT_STAGE'
                            elif 'third reading' in status_lower:
                                status_mapped = 'THIRD_READING'
                            elif 'senate' in status_lower:
                                status_mapped = 'SENATE'
                            elif 'royal assent' in status_lower:
                                status_mapped = 'ROYAL_ASSENT'
                            elif 'defeated' in status_lower:
                                status_mapped = 'DEFEATED'
                            elif 'withdrawn' in status_lower:
                                status_mapped = 'WITHDRAWN'

                        # Try to find sponsor MP
                        sponsor_mp = None
                        if sponsor_value != "N/A":
                            sponsor_mp = MemberOfParliament.objects.filter(name__icontains=sponsor_value).first()

                        # Prepare the bill data
                        subject_text = bill_subjects[i] if i < len(bill_subjects) and bill_subjects[
                            i] != "N/A" else "Unknown Subject"

                        # JUST CREATE THE BILL - NO DUPLICATE CHECKING
                        bill_obj = Bill.objects.create(
                            bill_number=bill_numbers[i],
                            parliament=parliament,
                            session=session_num,
                            subject=subject_text,
                            bill_type=bill_type_mapped,
                            sponsor=sponsor_mp,
                            current_status=status_mapped,
                            introduced_date=parsed_session_date if parsed_session_date else None,
                        )
                        created_count += 1
                        page_created += 1

                    except Exception as e:
                        error_count += 1
                        print(f"    ✗ Error saving bill {bill_numbers[i]}: {e}")

            if not offline:
                print(f"  Page {page}: Created {page_created}, Errors {error_count}")

            print(f"  Processed {len(bill_numbers)} bills. Total so far: {len(bills_data)}")
            page += 1

        except requests.exceptions.RequestException as e:
            print(f"  Request failed for page {page}: {e}")
            consecutive_failures += 1
            if consecutive_failures >= max_consecutive_failures:
                print(f"  Too many consecutive failures ({consecutive_failures}). Stopping.")
                break
            continue
        except Exception as e:
            print(f"  Unexpected error on page {page}: {e}")
            consecutive_failures += 1
            if consecutive_failures >= max_consecutive_failures:
                print(f"  Too many consecutive failures ({consecutive_failures}). Stopping.")
                break
            continue

    print(f"\nScraping completed. Total bills collected: {len(bills_data)}")

    if not offline:
        print(f"Database operations summary:")
        print(f"  ✓ Created: {created_count}")
        if error_count > 0:
            print(f"  ✗ Errors: {error_count}")

    if offline:
        df = pd.DataFrame(bills_data)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"parliamentary_bills_{timestamp}.csv"
        df.to_csv(filename, index=False)
        print(f"Data saved to: {os.path.abspath(filename)}")
        return df
    else:
        return f"Scraped {len(bills_data)} bills successfully! Created: {created_count}, Errors: {error_count}"


def scrape_committee_data(offline=False):
    """
    Scrapes committee details (adapted from your working version)
    """
    webpage_response = requests.get('https://www.ourcommons.ca/Committees/en/List#')
    soup = BeautifulSoup(webpage_response.content, 'html.parser')

    section_ids = {
        'standing-committees-section': 'STANDING',
        'special-committees-section': 'SPECIAL',
        'joint-committees-section': 'JOINT',
        'other-committees-section': 'OTHER'
    }

    committees_data = []

    for section_id, committee_type in section_ids.items():
        section = soup.find('div', id=section_id)
        if section:
            for item in section.find_all('div', class_='accordion-item'):
                acronym_elem = item.find('span', class_='committee-acronym-cell')
                name_elem = item.find('span', class_='committee-name')

                if acronym_elem and name_elem:
                    acronym = acronym_elem.text.strip()
                    name = name_elem.text.strip()

                    committees_data.append({
                        "Acronym": acronym,
                        "Name": name,
                        "Type": committee_type
                    })

                    if not offline:
                        Committee.objects.get_or_create(
                            committee_acronym=acronym,
                            defaults={
                                "committee_name": name,
                                "committee_type": committee_type,
                            }
                        )

    if offline:
        return pd.DataFrame(committees_data)
    else:
        return f"Committee data scraping complete! Processed {len(committees_data)} committees."


def scrape_committee_members(offline=False, delay_range=(1, 2)):
    """
    Scrapes committee members using your working URL pattern and CSS selectors
    """
    # Get all committees from database
    committees = Committee.objects.all()

    if not committees.exists():
        print("No committees found. Run scrape_committee_data() first.")
        return "No committees to process"

    all_members_data = []
    total_members_scraped = 0
    successful_committees = 0
    failed_committees = 0

    print(f"Scraping members for {committees.count()} committees...")

    # Setup session for requests
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    })

    for i, committee in enumerate(committees):
        print(f"Processing {committee.committee_acronym} ({i + 1}/{committees.count()})")

        # Add delay between requests
        if i > 0:
            delay = random.uniform(delay_range[0], delay_range[1])
            time.sleep(delay)

        try:
            # Use your working URL pattern
            url = f"https://www.ourcommons.ca/committees/en/{committee.committee_acronym}/Members?includeAssociates=True#AssociateMembers"

            response = session.get(url, timeout=30)

            if response.status_code != 200:
                print(f"  ✗ Failed to fetch {committee.committee_acronym} (status: {response.status_code})")
                failed_committees += 1
                continue

            soup = BeautifulSoup(response.content, 'html.parser')
            committee_members = []

            # Extract Chair(s) - using your working selectors
            chair_section = soup.find('div', id='committee-chair')
            if chair_section:
                for chair in chair_section.find_all('span', class_='committee-member-card hidden-xs'):
                    first_name_tag = chair.find('span', class_='first-name')
                    last_name_tag = chair.find('span', class_='last-name')

                    if first_name_tag and last_name_tag:
                        chair_name = f"{first_name_tag.text.strip()} {last_name_tag.text.strip()}"
                        committee_members.append({
                            'committee_acronym': committee.committee_acronym,
                            'member_name': chair_name,
                            'role': 'CHAIR'
                        })

            # Extract Vice-Chair(s)
            vice_chair_section = soup.find('div', id='committee-vice-chairs')
            if vice_chair_section:
                for vice_chair in vice_chair_section.find_all('span', class_='committee-member-card hidden-xs'):
                    first_name_tag = vice_chair.find('span', class_='first-name')
                    last_name_tag = vice_chair.find('span', class_='last-name')

                    if first_name_tag and last_name_tag:
                        vice_chair_name = f"{first_name_tag.text.strip()} {last_name_tag.text.strip()}"
                        committee_members.append({
                            'committee_acronym': committee.committee_acronym,
                            'member_name': vice_chair_name,
                            'role': 'VICE_CHAIR'
                        })

            # Extract Regular Committee Members
            # Get all members first, then filter out chairs/vice-chairs
            all_member_cards = soup.find_all('span', class_='committee-member-card hidden-xs')
            all_member_names = set()

            for member in all_member_cards:
                first_name_tag = member.find('span', class_='first-name')
                last_name_tag = member.find('span', class_='last-name')

                if first_name_tag and last_name_tag:
                    full_name = f"{first_name_tag.text.strip()} {last_name_tag.text.strip()}"
                    all_member_names.add(full_name)

            # Get names of chairs and vice-chairs to exclude from regular members
            chair_and_vice_names = {member['member_name'] for member in committee_members}

            # Add regular members (excluding chairs and vice-chairs)
            for member_name in all_member_names:
                if member_name not in chair_and_vice_names:
                    committee_members.append({
                        'committee_acronym': committee.committee_acronym,
                        'member_name': member_name,
                        'role': 'MEMBER'
                    })

            # Extract Associate Members
            associate_members_section = soup.find('div', id='associate-members')
            if associate_members_section:
                for associate in associate_members_section.find_all('span', class_='committee-member-card'):
                    name_tag = associate.find('span', class_='name')
                    if name_tag:
                        associate_name = name_tag.text.strip()
                        committee_members.append({
                            'committee_acronym': committee.committee_acronym,
                            'member_name': associate_name,
                            'role': 'ASSOCIATE'
                        })

            print(f"  ✓ Found {len(committee_members)} members for {committee.committee_acronym}")

            # Save to database if not offline
            if not offline and committee_members:
                saved_count = 0
                for member_data in committee_members:
                    # Clean the member name
                    cleaned_name = clean_mp_name_fixed(member_data['member_name'])

                    # Try to find the MP in the database
                    mp = MemberOfParliament.objects.filter(name=cleaned_name).first()

                    if mp:
                        # Create committee member record using the MP foreign key
                        CommitteeMember.objects.get_or_create(
                            committee=committee,
                            mp=mp,
                            defaults={
                                'role': member_data['role']
                            }
                        )
                        saved_count += 1
                    else:
                        print(f"    ⚠️  MP '{cleaned_name}' not found in database")

                print(f"    💾 Saved {saved_count}/{len(committee_members)} members to database")

            all_members_data.extend(committee_members)
            total_members_scraped += len(committee_members)
            successful_committees += 1

        except Exception as e:
            print(f"  ✗ Error processing {committee.committee_acronym}: {e}")
            failed_committees += 1
            continue

    print(f"\nCommittee member scraping completed!")
    print(f"✓ Successful committees: {successful_committees}")
    print(f"✗ Failed committees: {failed_committees}")
    print(f"📊 Total members scraped: {total_members_scraped}")

    if offline:
        return pd.DataFrame(all_members_data)
    else:
        return f"Scraped {total_members_scraped} committee members from {successful_committees}/{committees.count()} committees."


def populate_missing_bill_urls():
    """Populate bill_url for existing records that don't have it"""
    updated_count = 0

    for bill in Bill.objects.filter(bill_url__isnull=True):
        if bill.bill_number and bill.parliament:
            bill.bill_url = bill.generate_bill_url()
            bill.save()
            updated_count += 1

            if updated_count % 100 == 0:
                print(f"Updated {updated_count} bills...")

    print(f"Successfully populated URLs for {updated_count} bills")
    return updated_count

# Enhanced policy keyword mapping - now returns JSON-compatible lists
POLICY_AREAS = {
    'Healthcare & Medical': {
        'keywords': [
            'health', 'medical', 'hospital', 'doctor', 'nurse', 'patient', 'treatment',
            'medicine', 'pharmaceutical', 'drug', 'healthcare', 'clinic', 'surgery',
            'mental health', 'public health', 'epidemic', 'pandemic', 'vaccine',
            'medical device', 'health care', 'medicare', 'medicaid', 'disability'
        ],
        'weight': 1.0
    },

    'Economy & Finance': {
        'keywords': [
            'tax', 'economy', 'financial', 'budget', 'banking', 'investment', 'trade',
            'commerce', 'business', 'economic', 'fiscal', 'monetary', 'revenue',
            'expenditure', 'deficit', 'debt', 'inflation', 'employment', 'unemployment',
            'income', 'wage', 'salary', 'pension', 'retirement', 'securities', 'market'
        ],
        'weight': 1.0
    },

    'Environment & Climate': {
        'keywords': [
            'environment', 'climate', 'pollution', 'emission', 'carbon', 'greenhouse',
            'renewable', 'energy', 'conservation', 'wildlife', 'biodiversity',
            'water', 'air quality', 'toxic', 'waste', 'recycling', 'sustainability',
            'forestry', 'fisheries', 'marine', 'arctic', 'oil', 'gas', 'mining'
        ],
        'weight': 1.0
    },

    'Justice & Crime': {
        'keywords': [
            'criminal', 'crime', 'justice', 'court', 'judge', 'police', 'prison',
            'sentence', 'penalty', 'law enforcement', 'safety', 'security',
            'violence', 'terrorism', 'fraud', 'corruption', 'rights', 'legal',
            'prosecution', 'defense', 'bail', 'parole', 'rehabilitation'
        ],
        'weight': 1.0
    },

    'Education & Research': {
        'keywords': [
            'education', 'school', 'university', 'student', 'teacher', 'learning',
            'research', 'science', 'technology', 'innovation', 'academic',
            'curriculum', 'scholarship', 'training', 'skill', 'literacy',
            'knowledge', 'study', 'campus', 'degree', 'diploma'
        ],
        'weight': 1.0
    },

    'Immigration & Citizenship': {
        'keywords': [
            'immigration', 'immigrant', 'refugee', 'citizenship', 'visa', 'border',
            'foreign', 'temporary', 'permanent', 'resident', 'deportation',
            'asylum', 'migration', 'naturalization', 'entry', 'admission'
        ],
        'weight': 1.0
    },

    'Transportation & Infrastructure': {
        'keywords': [
            'transport', 'infrastructure', 'road', 'highway', 'bridge', 'transit',
            'railway', 'airport', 'port', 'shipping', 'aviation', 'vehicle',
            'traffic', 'construction', 'public works', 'maintenance', 'repair'
        ],
        'weight': 1.0
    },

    'Social Services & Welfare': {
        'keywords': [
            'social', 'welfare', 'benefit', 'assistance', 'support', 'child',
            'family', 'housing', 'poverty', 'homeless', 'elderly', 'senior',
            'youth', 'community', 'service', 'program', 'aid', 'subsidy'
        ],
        'weight': 1.0
    },

    'Agriculture & Food': {
        'keywords': [
            'agriculture', 'farming', 'food', 'crop', 'livestock', 'dairy',
            'meat', 'grain', 'produce', 'rural', 'farmer', 'agricultural',
            'nutrition', 'safety', 'inspection', 'organic', 'pesticide'
        ],
        'weight': 1.0
    },

    'Government Operations': {
        'keywords': [
            'government', 'administration', 'bureaucracy', 'civil service',
            'public service', 'federal', 'provincial', 'municipal', 'parliament',
            'election', 'voting', 'democracy', 'transparency', 'accountability',
            'information', 'access', 'privacy', 'official', 'minister'
        ],
        'weight': 1.0
    },

    'Indigenous Affairs': {
        'keywords': [
            'indigenous', 'first nation', 'aboriginal', 'native', 'inuit', 'métis',
            'treaty', 'reserve', 'land claim', 'self-government', 'traditional',
            'cultural', 'reconciliation', 'rights', 'sovereignty'
        ],
        'weight': 1.2
    },

    'Defense & Veterans': {
        'keywords': [
            'defense', 'military', 'armed forces', 'veteran', 'soldier', 'navy',
            'army', 'air force', 'peacekeeping', 'security', 'intelligence',
            'national security', 'warfare', 'conflict', 'peace'
        ],
        'weight': 1.0
    },

    'Communications & Media': {
        'keywords': [
            'communication', 'broadcasting', 'media', 'internet', 'telecommunication',
            'radio', 'television', 'digital', 'technology', 'information technology',
            'cyber', 'online', 'network', 'spectrum', 'wireless'
        ],
        'weight': 1.0
    },

    'International Relations': {
        'keywords': [
            'international', 'foreign', 'treaty', 'agreement', 'diplomatic',
            'embassy', 'consulate', 'trade agreement', 'sanctions', 'cooperation',
            'bilateral', 'multilateral', 'global', 'world', 'nations'
        ],
        'weight': 1.0
    }
}


def scrape_bill_content(bill_url, max_retries=3):
    """Scrape the full content of a bill page for classification"""
    if not bill_url:
        return None

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    })

    for attempt in range(max_retries):
        try:
            response = session.get(bill_url, timeout=30)
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')

                content_parts = []

                title = soup.find('h1')
                if title:
                    content_parts.append(title.get_text(strip=True))

                summary = soup.find('div', class_='bill-summary') or soup.find('div', class_='summary')
                if summary:
                    content_parts.append(summary.get_text(strip=True))

                short_title = soup.find('div', class_='short-title')
                if short_title:
                    content_parts.append(short_title.get_text(strip=True))

                main_content = soup.find('div', class_='main-content') or soup.find('main')
                if main_content:
                    text = main_content.get_text(strip=True)
                    content_parts.append(text[:2000])

                progress = soup.find('div', class_='progress') or soup.find('div', class_='status')
                if progress:
                    content_parts.append(progress.get_text(strip=True))

                return ' '.join(content_parts)

            else:
                print(f"Failed to fetch {bill_url}: Status {response.status_code}")

        except Exception as e:
            print(f"Attempt {attempt + 1} failed for {bill_url}: {e}")
            if attempt < max_retries - 1:
                time.sleep(random.uniform(1, 3))

    return None


def classify_bill_content(content, bill_subject=""):
    """Classify bill content into policy areas - returns JSON-compatible data"""
    if not content:
        return [], "", 0.0

    full_text = f"{bill_subject} {content}".lower()
    policy_scores = {}

    for policy_area, config in POLICY_AREAS.items():
        score = 0
        keywords_found = []

        for keyword in config['keywords']:
            count = len(re.findall(r'\b' + re.escape(keyword.lower()) + r'\b', full_text))
            if count > 0:
                keywords_found.append((keyword, count))
                score += config['weight'] * (count * 0.5 + 0.5)

        if score > 0:
            policy_scores[policy_area] = {
                'score': score,
                'keywords': keywords_found
            }

    if not policy_scores:
        return [], "", 0.0

    sorted_policies = sorted(policy_scores.items(), key=lambda x: x[1]['score'], reverse=True)
    primary_policy = sorted_policies[0][0]
    primary_score = sorted_policies[0][1]['score']

    total_score = sum(item[1]['score'] for item in sorted_policies)
    confidence = min(primary_score / total_score, 1.0) if total_score > 0 else 0.0

    # Return only policy names as a list (JSON-compatible)
    relevant_tags = [policy for policy, data in sorted_policies if data['score'] > 1.0]

    return relevant_tags, primary_policy, confidence


def classify_bills_batch(bill_queryset=None, delay_range=(1, 3)):
    """Classify multiple bills in batch using the new model structure"""
    if bill_queryset is None:
        bill_queryset = Bill.objects.filter(auto_classified=False)

    total_bills = bill_queryset.count()
    processed = 0
    classified = 0
    errors = 0

    print(f"Starting classification of {total_bills} bills...")

    for bill in bill_queryset:
        try:
            print(f"Processing {bill.bill_number} ({processed + 1}/{total_bills})")

            if processed > 0:
                delay = random.uniform(delay_range[0], delay_range[1])
                time.sleep(delay)

            content = scrape_bill_content(bill.bill_url)

            if content:
                tags, primary_area, confidence = classify_bill_content(content, bill.subject)

                # Update the bill record with new field names
                bill.policy_tags = tags  # Store as JSON list
                bill.primary_policy_area = primary_area  # Store as string
                bill.classification_confidence = confidence
                bill.auto_classified = True
                bill.classification_date = datetime.now()
                bill.save()

                classified += 1
                print(f"  ✓ Classified as: {primary_area} (confidence: {confidence:.2f})")
                print(f"  ✓ Tags: {', '.join(tags[:3])}...")
            else:
                print(f"  ✗ Could not scrape content for {bill.bill_number}")
                errors += 1

            processed += 1

            if processed % 10 == 0:
                print(f"\nProgress: {processed}/{total_bills} processed, {classified} classified, {errors} errors\n")

        except Exception as e:
            print(f"  ✗ Error processing {bill.bill_number}: {e}")
            errors += 1
            processed += 1

    print(f"\nClassification complete!")
    print(f"Total processed: {processed}")
    print(f"Successfully classified: {classified}")
    print(f"Errors: {errors}")

    return {
        'processed': processed,
        'classified': classified,
        'errors': errors
    }


def create_policy_topics():
    """Create PolicyTopic records from the POLICY_AREAS dictionary"""
    created_count = 0

    for policy_name, config in POLICY_AREAS.items():
        keywords_str = ', '.join(config['keywords'])

        topic, created = PolicyTopic.objects.get_or_create(
            name=policy_name,
            defaults={
                'keywords': keywords_str,
                'color': '#6B7280'  # Default gray color
            }
        )

        if created:
            created_count += 1
            print(f"Created policy topic: {policy_name}")

    print(f"Policy topic creation complete. Created {created_count} new topics.")
    return created_count


def update_vote_policy_tags():
    """Update policy tags for votes based on related bills"""
    updated_count = 0

    for vote in VoteRecord.objects.filter(related_bill__isnull=False):
        if vote.related_bill and vote.related_bill.policy_tags:
            vote.policy_tags = vote.related_bill.policy_tags
            vote.save()
            updated_count += 1

            if updated_count % 50 == 0:
                print(f"Updated {updated_count} vote records...")

    print(f"Updated policy tags for {updated_count} vote records")
    return updated_count


def link_votes_to_bills():
    """
    Link vote records to related bills based on vote subject text
    """
    linked_count = 0

    # Get votes that don't have related bills yet
    votes_without_bills = VoteRecord.objects.filter(related_bill__isnull=True)

    print(f"Processing {votes_without_bills.count()} votes without related bills...")

    for vote in votes_without_bills:
        # Look for bill numbers in the vote subject
        bill_matches = re.findall(r'\b([CS]-\d+)\b', vote.subject.upper())

        if bill_matches:
            bill_number = bill_matches[0]  # Take first match

            # Find matching bill in same parliament
            bill = Bill.objects.filter(
                bill_number__icontains=bill_number,
                parliament=vote.parliament
            ).first()

            if bill:
                vote.related_bill = bill
                vote.save()
                linked_count += 1

                if linked_count % 50 == 0:
                    print(f"  Linked {linked_count} votes to bills...")

    print(f"✅ Linked {linked_count} votes to bills")
    return linked_count


# Utility functions for data analysis


def get_party_political_spectrum():
    """
    Map Canadian parties to political spectrum based on established positions
    """
    return {
        'Conservative Party of Canada': 'CONSERVATIVE',
        'Conservative': 'CONSERVATIVE',
        'Liberal Party of Canada': 'MODERATE',
        'Liberal': 'MODERATE',
        'New Democratic Party': 'PROGRESSIVE',
        'NDP': 'PROGRESSIVE',
        'Bloc Québécois': 'MODERATE',  # Quebec nationalism, mixed on other issues
        'Green Party of Canada': 'PROGRESSIVE',
        'Green': 'PROGRESSIVE',
        'People\'s Party of Canada': 'CONSERVATIVE'
    }


# Add these functions to your scrapers.py file

# Add these functions to your scrapers.py file

def get_high_confidence_indicators():
    """
    Return lists of terms that clearly indicate progressive or conservative positions
    """

    progressive_terms = [
        'carbon tax', 'climate action', 'climate change', 'gun control', 'firearms control',
        'universal healthcare', 'public healthcare', 'minimum wage increase', 'workers rights',
        'refugee protection', 'asylum seekers', 'indigenous reconciliation', 'indigenous rights',
        'affordable housing', 'social housing', 'public transit', 'environmental protection',
        'renewable energy', 'clean energy', 'social program', 'employment insurance',
        'child care', 'childcare', 'parental leave', 'pay equity', 'gender equality',
        'human rights', 'lgbtq', 'diversity', 'inclusion', 'anti-discrimination'
    ]

    conservative_terms = [
        'tax reduction', 'tax cut', 'lower taxes', 'deregulation', 'red tape reduction',
        'military spending', 'defence spending', 'border security', 'immigration control',
        'tough on crime', 'law and order', 'balanced budget', 'deficit reduction',
        'free trade', 'pipeline approval', 'oil drilling', 'resource development',
        'government efficiency', 'privatization', 'repeal carbon tax', 'small government',
        'fiscal responsibility', 'economic growth', 'business development', 'job creation'
    ]

    return progressive_terms, conservative_terms


def analyze_party_voting_patterns(vote_record):
    """
    Analyze how different parties voted to determine if it's partisan or bipartisan
    """
    party_votes = {}

    # Get all MP votes for this vote record
    for mp_vote in vote_record.mpvote_set.select_related('mp').all():
        # Use political_affiliation field instead of party
        party = mp_vote.mp.political_affiliation
        if party not in party_votes:
            party_votes[party] = {'YEA': 0, 'NAY': 0, 'PAIRED': 0, 'ABSENT': 0, 'total': 0}

        party_votes[party][mp_vote.vote] += 1
        if mp_vote.vote in ['YEA', 'NAY']:
            party_votes[party]['total'] += 1

    # Calculate each party's majority position
    party_positions = {}
    for party, votes in party_votes.items():
        if votes['total'] >= 3:  # Only consider parties with meaningful representation
            yea_percentage = (votes['YEA'] / votes['total']) * 100 if votes['total'] > 0 else 0

            if yea_percentage >= 70:
                party_positions[party] = 'YEA'
            elif yea_percentage <= 30:
                party_positions[party] = 'NAY'
            else:
                party_positions[party] = 'SPLIT'

    # Check if major parties agree (indicating bipartisan support)
    major_parties = [
        'Conservative Party of Canada', 'Liberal Party of Canada',
        'Conservative', 'Liberal'
    ]
    conservative_pos = None
    liberal_pos = None

    for party in party_positions.keys():
        if any(term in party for term in ['Conservative', 'conservative']):
            conservative_pos = party_positions[party]
        elif any(term in party for term in ['Liberal', 'liberal']):
            liberal_pos = party_positions[party]

    is_bipartisan = (
            conservative_pos and liberal_pos and
            conservative_pos == liberal_pos and
            conservative_pos != 'SPLIT'
    )

    return {
        'is_bipartisan': is_bipartisan,
        'party_positions': party_positions,
        'unanimous_direction': conservative_pos if is_bipartisan else None,
        'party_vote_breakdown': party_votes
    }


def classify_bipartisan_vote(vote_record):
    """
    Classify bipartisan votes into appropriate categories
    """
    subject = vote_record.subject.lower()

    # Procedural indicators
    procedural_terms = [
        'motion to adjourn', 'appointment of', 'committee report', 'report of the committee',
        'sitting calendar', 'order of business', 'parliamentary procedure', 'motion for closure',
        'time allocation', 'ways and means', 'government business no', 'orders of the day'
    ]

    # Ceremonial indicators
    ceremonial_terms = [
        'national day', 'remembrance', 'commemoration', 'recognition of', 'in memory of',
        'condolences', 'congratulations', 'naming of', 'post office', 'heritage designation',
        'tribute to', 'honouring', 'celebrating'
    ]

    # Crisis response indicators
    crisis_terms = [
        'emergency', 'disaster relief', 'pandemic', 'urgent measures', 'covid',
        'crisis response', 'immediate action', 'emergency funding', 'natural disaster',
        'public health emergency', 'relief measures'
    ]

    # Technical indicators
    technical_terms = [
        'technical amendment', 'administrative', 'modernization', 'updating',
        'efficiency', 'implementation', 'routine maintenance', 'housekeeping',
        'clarification', 'correction'
    ]

    if any(term in subject for term in procedural_terms):
        return 'PROCEDURAL'
    elif any(term in subject for term in ceremonial_terms):
        return 'CEREMONIAL'
    elif any(term in subject for term in crisis_terms):
        return 'CRISIS_RESPONSE'
    elif any(term in subject for term in technical_terms):
        return 'TECHNICAL'
    else:
        return 'BIPARTISAN_SUBSTANTIVE'  # Real policy agreement across parties


def classify_partisan_vote(vote_record, party_analysis):
    """
    Classify clearly partisan votes using text analysis
    """
    progressive_terms, conservative_terms = get_high_confidence_indicators()

    subject = vote_record.subject.lower()

    # Count matches for each ideology
    progressive_matches = sum(1 for term in progressive_terms if term in subject)
    conservative_matches = sum(1 for term in conservative_terms if term in subject)

    # Determine which party voted YEA vs NAY to understand the vote direction
    party_positions = party_analysis['party_positions']

    # If we have clear text indicators, use them
    if progressive_matches > conservative_matches and progressive_matches > 0:
        return 'PROGRESSIVE_INITIATIVE'
    elif conservative_matches > progressive_matches and conservative_matches > 0:
        return 'CONSERVATIVE_INITIATIVE'
    else:
        # If text is unclear, try to infer from party positions
        conservative_voted_yea = any(
            party_positions.get(party) == 'YEA'
            for party in ['Conservative Party of Canada', 'Conservative']
        )
        liberal_voted_yea = any(
            party_positions.get(party) == 'YEA'
            for party in ['Liberal Party of Canada', 'Liberal']
        )

        # If conservatives and liberals voted opposite ways, it's probably ideological
        if conservative_voted_yea and not liberal_voted_yea:
            return 'CONSERVATIVE_INITIATIVE'
        elif liberal_voted_yea and not conservative_voted_yea:
            return 'PROGRESSIVE_INITIATIVE'
        else:
            return 'PARTISAN_UNCLEAR'


def classify_vote_with_bipartisan_handling(vote_record):
    """
    Main function to classify any vote record
    """
    try:
        # First, analyze party voting patterns
        party_analysis = analyze_party_voting_patterns(vote_record)

        if party_analysis['is_bipartisan']:
            return classify_bipartisan_vote(vote_record)
        else:
            return classify_partisan_vote(vote_record, party_analysis)

    except Exception as e:
        print(f"Error classifying vote {vote_record.vote_number}: {e}")
        return 'CLASSIFICATION_ERROR'


def get_stance_label(progressive_percentage):
    """
    Convert percentage to human-readable stance label
    """
    if progressive_percentage >= 80:
        return 'STRONGLY_PROGRESSIVE'
    elif progressive_percentage >= 60:
        return 'MOSTLY_PROGRESSIVE'
    elif progressive_percentage >= 40:
        return 'MODERATE'
    elif progressive_percentage >= 20:
        return 'MOSTLY_CONSERVATIVE'
    else:
        return 'STRONGLY_CONSERVATIVE'


def calculate_mp_stance_with_bipartisan_handling(mp_id, policy_area):
    """
    Calculate MP's stance on a policy area while properly handling bipartisan votes
    """
    try:
        mp = MemberOfParliament.objects.get(id=mp_id)
        # Use icontains on the policy_tags field converted to text instead of contains lookup
        votes = MPVote.objects.filter(mp=mp).select_related('vote_record')

        # Filter votes that have the policy area in their tags
        relevant_votes = []
        for vote in votes:
            if vote.vote_record.policy_tags and policy_area in vote.vote_record.policy_tags:
                relevant_votes.append(vote)

        ideological_scores = {'PROGRESSIVE': 0, 'CONSERVATIVE': 0}
        bipartisan_participation = 0
        vote_classifications = {
            'PROCEDURAL': 0,
            'CEREMONIAL': 0,
            'CRISIS_RESPONSE': 0,
            'TECHNICAL': 0,
            'BIPARTISAN_SUBSTANTIVE': 0
        }

        for vote in relevant_votes:
            classification = classify_vote_with_bipartisan_handling(vote.vote_record)

            # Only count clearly ideological votes for stance calculation
            if classification in ['PROGRESSIVE_INITIATIVE', 'CONSERVATIVE_INITIATIVE']:
                if vote.vote == 'YEA':
                    position = classification.replace('_INITIATIVE', '')
                elif vote.vote == 'NAY':
                    # Flip position for NAY votes
                    position = 'CONSERVATIVE' if 'PROGRESSIVE' in classification else 'PROGRESSIVE'
                else:
                    continue  # Skip PAIRED/ABSENT for stance calculation

                ideological_scores[position] += 1

            elif classification in ['BIPARTISAN_SUBSTANTIVE', 'CRISIS_RESPONSE']:
                # Count bipartisan participation separately
                if vote.vote in ['YEA', 'NAY']:
                    bipartisan_participation += 1

            # Track all classification types
            if classification in vote_classifications:
                vote_classifications[classification] += 1

        total_ideological = sum(ideological_scores.values())
        total_votes = len(relevant_votes)

        if total_ideological < 3:  # Need minimum votes for reliable assessment
            return {
                'stance': 'INSUFFICIENT_DATA',
                'confidence': 'LOW',
                'total_votes': total_votes,
                'ideological_votes': total_ideological,
                'bipartisan_participation': bipartisan_participation,
                'vote_breakdown': vote_classifications,
                'progressive_percentage': 0
            }

        progressive_percentage = (ideological_scores['PROGRESSIVE'] / total_ideological) * 100

        return {
            'stance': get_stance_label(progressive_percentage),
            'progressive_percentage': progressive_percentage,
            'ideological_votes': total_ideological,
            'bipartisan_participation': bipartisan_participation,
            'confidence': 'HIGH' if total_ideological >= 10 else 'MEDIUM',
            'total_votes': total_votes,
            'vote_breakdown': vote_classifications,
            'raw_scores': ideological_scores
        }

    except Exception as e:
        print(f"Error calculating stance for MP {mp_id} on {policy_area}: {e}")
        return {
            'stance': 'ERROR',
            'confidence': 'LOW',
            'error': str(e)
        }


def get_mp_policy_summary_enhanced(mp_id):
    """
    Get comprehensive policy summary for an MP across all policy areas
    """
    try:
        mp = MemberOfParliament.objects.get(id=mp_id)

        # Get all policy areas this MP has voted on - SQLite compatible approach
        policy_areas = set()
        mp_votes = MPVote.objects.filter(mp=mp).select_related('vote_record')

        for vote in mp_votes:
            if vote.vote_record.policy_tags:
                policy_areas.update(vote.vote_record.policy_tags)

        summary = {
            'mp_name': mp.name,
            'political_affiliation': mp.political_affiliation,  # Use correct field
            'policy_stances': {}
        }

        for policy in policy_areas:
            stance_data = calculate_mp_stance_with_bipartisan_handling(mp_id, policy)
            summary['policy_stances'][policy] = stance_data

        return summary

    except Exception as e:
        return {
            'error': f"Could not generate summary for MP {mp_id}: {e}"
        }


def test_classification_system():
    """
    Test the classification system on a sample of votes
    """
    print("Testing vote classification system...")

    # Get a sample of votes to test
    sample_votes = VoteRecord.objects.all()[:20]

    for vote in sample_votes:
        classification = classify_vote_with_bipartisan_handling(vote)
        party_analysis = analyze_party_voting_patterns(vote)

        print(f"\nVote {vote.vote_number}: {vote.subject[:60]}...")
        print(f"  Classification: {classification}")
        print(f"  Bipartisan: {party_analysis['is_bipartisan']}")
        print(f"  Party positions: {party_analysis['party_positions']}")


# Example usage functions for testing
def run_classification_tests():
    """
    Run comprehensive tests of the classification system
    """
    print("=== TESTING VOTE CLASSIFICATION SYSTEM ===")

    # Test 1: Overall system test
    test_classification_system()

    # Test 2: MP stance calculation
    print("\n=== TESTING MP STANCE CALCULATION ===")

    # Get a sample MP
    sample_mp = MemberOfParliament.objects.first()
    if sample_mp:
        print(f"Testing stance calculation for {sample_mp.name}")
        summary = get_mp_policy_summary_enhanced(sample_mp.id)

        print(f"Policy stances for {summary.get('mp_name', 'Unknown')}:")
        for policy, stance_data in summary.get('policy_stances', {}).items():
            print(f"  {policy}: {stance_data.get('stance', 'Unknown')} "
                  f"({stance_data.get('confidence', 'Unknown')} confidence, "
                  f"{stance_data.get('ideological_votes', 0)} ideological votes)")


def get_simple_mp_stance_for_frontend(mp_id, policy_area):
    """
    Simple function that returns just stance and confidence for frontend display
    """

    stance_data = calculate_mp_stance_with_bipartisan_handling(mp_id, policy_area)

    return {
        'stance': stance_data['stance'],
        'confidence': stance_data['confidence'],
        'progressive_percentage': stance_data.get('progressive_percentage', 0)
    }


def compare_mp_stances(mp_names, policy_areas):
    """
    Compare MPs using the ideological stance system
    """
    from core.scrapers import calculate_mp_stance_with_bipartisan_handling

    comparison = {}

    for mp_name in mp_names:
        mp = MemberOfParliament.objects.get(name=mp_name)
        comparison[mp_name] = {}

        for policy in policy_areas:
            stance_data = calculate_mp_stance_with_bipartisan_handling(mp.id, policy)
            comparison[mp_name][policy] = {
                'stance': stance_data['stance'],
                'progressive_percentage': stance_data['progressive_percentage'],
                'confidence': stance_data['confidence']
            }

    return comparison


# Main execution functions

def run_full_data_scrape():
    """Run all scraping functions in sequence"""
    print("Starting comprehensive parliamentary data scrape...")

    print("\n1. Creating policy topics...")
    create_policy_topics()

    print("\n2. Scraping MP details...")
    scrape_members_of_parliament_details()

    print("\n3. Scraping vote records...")
    scrape_all_parliament_votes()

    print("\n4. Scraping individual MP votes...")
    scrape_mp_vote_details_table_based()

    print("\n5. Scraping bills...")
    scrape_bills()

    print("\n6. Populating missing bill URLs...")
    populate_missing_bill_urls()

    print("\n7. Scraping committee data...")
    scrape_committee_data()

    print("\n8. Classifying bills by policy area...")
    classify_bills_batch()

    print("\n9. Updating vote policy tags...")
    update_vote_policy_tags()

    print("\nData scraping complete!")


if __name__ == "__main__":
    # Example usage
    print("Parliamentary data scraping functions loaded.")
    print("Run run_full_data_scrape() to execute all scraping functions.")
    print("Or run individual functions as needed.")

##### Debug section #####


