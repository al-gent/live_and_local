from openai import OpenAI
from bs4 import BeautifulSoup
import time

def get_soup(url, driver):
    driver.get(url)
    time.sleep(1)
    html = driver.page_source
    return BeautifulSoup(html, 'html.parser')

def parse_soup(soup, tag_class):
    return soup.select(f'[class*="{tag_class}"]')


def whats_the_class(soup):
    client = OpenAI()
    
    # Truncate the HTML to avoid token limits and focus on relevant parts
    html_str = str(soup)  # First 10k chars usually contain the main content
    
    completion = client.chat.completions.create(
        model="gpt-4o",  # Cheaper and faster for this task
        messages=[{
            "role": "system", 
            "content": "You are an expert at analyzing HTML structure. Return only the CSS class name(s) used for headliner/artist names, nothing else."
        }, {
            "role": "user", 
            "content": f"""Analyze this venue website HTML and find the CSS class used specifically for headliner/artist names.

Look for patterns like:
- Elements containing artist names
- Event titles with performer names  
- Headliner sections

Return ONLY the class name(s). Examples of good responses:
- event-title
- artist-name headliner
- fs-12 rhp-event__title

HTML:
{html_str}"""
        }],
        temperature=0,
        # max_tokens=50
    )
    
    return completion.choices[0].message.content.strip()


def get_artists_from_url(venue_url, driver, known_classes):
    # scrape the site to get the soup
    soup = get_soup(venue_url, driver)
    print('got the soup 🥳')
    headliners=[]
    # if you know the tag, use it
    if known_classes.get(venue_url):
        print('I already know the tags this website uses!')
        tag_class = known_classes[venue_url]
        headliners = parse_soup(soup, tag_class)
        return headliners
    # else ask chat for the tag
    else:
        print('asking chat')
        chat_says = whats_the_class(soup)
        print('chat thinks the tag is', chat_says)

        #validate that chat_says i actually a tag 😳

    # Validate that chat_says is actually a valid selector
    try:
        test_elements = soup.select(chat_says)  # Try to use the selector
        if test_elements:  # If it finds elements, it's valid
            print(f'Valid selector! Found {len(test_elements)} elements')

            headliners = parse_soup(soup, chat_says)
            
            # Validate results before saving
            if headliners and len(headliners) > 0:
                print(f'found {len(headliners)} headliners, saving class')
                known_classes[venue_url] = chat_says
            else:
                print('no headliners found, not saving class')
        else:
            print('Selector is valid but found no elements')
            
    except Exception as e:
        print(f'Chat gave invalid selector: {chat_says}')
        print(f'Error: {e}')
    if headliners:
        headliners_text = [headliner.text for headliner in headliners]
        return headliners_text
    else:
        return headliners

