# Geo-Data Pipeline Tracker

> **Goal:** Build geocoded datasets for everything people want to find "near me," visualized on a map.
> **Collection methods:** Free/cheap APIs, open data portals, RSS/structured feeds, and human-browsing fallback via SpiritPool/EDN.

---

## ✅ In Progress

### 1. Job Listings (Geocoded)
- **Status:** Active
- **Sources:** Adzuna API (free tier), Remotive, Jobicy, USAJobs API
- **Notes:** Already integrated into First Helios / OpenClaw pipeline

### 2. Meal Deals
- **Status:** Planned
- **Sources:** No reliable free API exists
- **Collection strategy:** Human browsing (SpiritPool). Restaurant websites, Groupon local, and chain deal pages are the primary targets. Structure a schema for: restaurant name, deal description, valid days/times, geocode.
- **Supplemental:** Yelp Fusion API (free 5k calls/day) for restaurant metadata; deals themselves require browsing.

---

## 🔲 To Explore

### 3. Free / Community Events
- **What:** Concerts, farmers markets, festivals, meetups, open mics, library programs, volunteer days
- **Free APIs / Feeds:**
  - Eventbrite API (free, requires approval) — structured event data with coords
  - Meetup Pro API (limited free access, GraphQL) — tech/hobby/community groups
  - Facebook Events — no public API; browsing fallback required
  - Library calendar RSS feeds — most public library systems publish iCal or RSS
  - Eventful / PredictHQ (freemium, limited free tier)
- **Open data:** Many cities publish event permit data (e.g., Austin Open Data Portal)
- **Browsing fallback:** Facebook Events, Nextdoor, local news "things to do" pages
- **Schema needs:** Event name, datetime, location, geocode, category, cost (free/paid), recurrence

### 4. Gas Prices
- **What:** Real-time station-level fuel pricing
- **Free APIs / Feeds:**
  - GasBuddy — no official public API, but structured pages amenable to browsing collection
  - AAA Gas Prices — regional averages only, not station-level
  - U.S. EIA API (free, key required) — wholesale/regional, not retail station-level
  - CollectAPI Gas Prices (freemium, \~$10/mo for station-level)
- **Browsing fallback:** GasBuddy station pages, Google Maps fuel overlay
- **Schema needs:** Station name, address, geocode, fuel type, price, timestamp

### 5. Happy Hours
- **What:** Time-limited drink and food specials at bars and restaurants
- **Free APIs / Feeds:**
  - None reliable. The Happy Hour app existed but API is not public.
  - Yelp Fusion — can identify bars/restaurants but does not surface happy hour details
- **Browsing fallback:** Primary method. Target: individual restaurant websites, local food blogs, "best happy hours in [city]" articles, Google Business Profile descriptions
- **Schema needs:** Venue name, geocode, days, start/end time, specials list, verified date

### 6. Free Food / Food Banks / Mutual Aid
- **What:** Pantries, community fridges, soup kitchens, mutual aid distros
- **Free APIs / Feeds:**
  - Feeding America Food Bank Locator — structured, scrapeable
  - USDA Food & Nutrition Service — WIC/SNAP office locator API
  - FoodPantries.org — directory, no API
  - FreeFridge.org / community fridge maps — varies by city
- **Open data:** 211.org (United Way) — social services locator with some structured feeds
- **Browsing fallback:** Mutual aid spreadsheets (often Google Sheets shared publicly), Nextdoor, local subreddits
- **Schema needs:** Org name, address, geocode, type (pantry/fridge/kitchen), hours, eligibility, freshness date

### 7. EV Charging Stations
- **What:** Public EV chargers, connector types, availability
- **Free APIs / Feeds:**
  - OpenChargeMap API — **free, open-source, global**, CC-licensed. Best starting point.
  - AFDC Alternative Fuels Station Locator (DOE/NREL) — free API key, U.S.-focused, includes EV + other alt fuels
  - PlugShare — no public API; browsing fallback
- **Schema needs:** Station name, address, geocode, connector types, network, num ports, pricing, real-time availability (if supported)

### 8. Garage Sales / Estate Sales
- **What:** Hyperlocal, time-bound secondhand sales
- **Free APIs / Feeds:**
  - EstateSales.NET — structured listings, no official API; browsing-friendly
  - GarageSaleFinder.com — same situation
  - Craigslist garage sale section — structured enough for browsing collection
  - Facebook Marketplace / Yard Sale groups — browsing only
- **Browsing fallback:** Primary method for all sources above
- **Schema needs:** Address, geocode, date(s), time range, description/highlights, source URL

### 9. Open Houses / Rent Drops
- **What:** Homes with walk-in viewings or recent price reductions
- **Free APIs / Feeds:**
  - Zillow — no longer offers free API; browsing fallback
  - Redfin — no public API; data downloads available for aggregate stats only
  - Realtor.com API (RapidAPI) — freemium, limited calls
  - HUD Fair Market Rent data — free, annual, for rent benchmarks only
  - OpenStreetMap + Overpass API — building footprints, not listings
- **Browsing fallback:** Zillow, Redfin, Apartments.com filtered to open houses and recent price drops
- **Schema needs:** Address, geocode, list price, previous price, event type (open house / price drop), datetime, bedrooms, sqft, source

### 10. Free Parking / Permit-Free Zones
- **What:** Free lots, street parking zones, meter-free areas, time limits
- **Free APIs / Feeds:**
  - OpenStreetMap — parking lots and garages tagged; query via Overpass API (free)
  - City open data portals — many cities publish parking meter locations and zones (Austin does)
  - ParkMe / SpotHero — no free API for street parking
- **Browsing fallback:** City DOT maps, Google Street View for signage (manual)
- **Schema needs:** Location, geocode, type (lot/street/garage), cost (free/metered), time limit, hours enforced

### 11. Public Restrooms
- **What:** Publicly accessible restrooms
- **Free APIs / Feeds:**
  - Refuge Restrooms API — **free, open-source**, focuses on safe/accessible restrooms (includes all-gender)
  - OpenStreetMap — `amenity=toilets` tag; query via Overpass API (free)
  - Flush App — no public API
- **Browsing fallback:** Minimal need given OSM coverage
- **Schema needs:** Location, geocode, accessible (bool), gender-neutral (bool), requires purchase (bool), hours

### 12. Free Wi-Fi Hotspots
- **What:** Free public internet locations — libraries, cafes, city-provided
- **Free APIs / Feeds:**
  - OpenWiFiMap — open data, limited coverage
  - WifiMap app — crowdsourced, no public API
  - OpenStreetMap — `internet_access=wlan` + `internet_access:fee=no` via Overpass (free)
  - City open data — many cities publish municipal Wi-Fi locations
- **Browsing fallback:** Library system websites, "free wifi near me" local guides
- **Schema needs:** Location name, geocode, provider, speed tier (if known), hours, indoor/outdoor

### 13. Blood Drives / Donation Centers
- **What:** Red Cross drives, plasma centers, blood banks
- **Free APIs / Feeds:**
  - American Red Cross — blood drive locator is structured, no official API but stable HTML
  - Vitalant, OneBlood — regional blood bank locators
  - DonatingPlasma.org — directory
- **Browsing fallback:** Red Cross and regional blood bank event pages
- **Schema needs:** Org name, address, geocode, type (whole blood / plasma / platelets), date(s), hours, appointment required (bool)

### 14. Pet-Friendly Spaces
- **What:** Dog parks, pet-allowed patios, off-leash areas, pet water stations
- **Free APIs / Feeds:**
  - BringFido API — **free tier available**, pet-friendly venues database
  - OpenStreetMap — `leisure=dog_park` via Overpass (free)
  - Yelp Fusion — filter by "dogs_allowed" attribute (free tier)
- **Browsing fallback:** City parks department pages, local "dog-friendly patio" blog posts
- **Schema needs:** Name, geocode, type (park/patio/trail), off-leash (bool), hours, fenced (bool)

### 15. Pickup Sports / Open Courts
- **What:** Basketball courts, tennis courts, soccer fields, volleyball — public and open-access
- **Free APIs / Feeds:**
  - OpenStreetMap — `leisure=pitch`, `sport=*` via Overpass (free) — very good coverage
  - City parks & rec open data — many publish facility inventories
  - Courts of the World (tennis) — structured directory
- **Browsing fallback:** City rec department sites, Google Maps POI data
- **Schema needs:** Location, geocode, sport type, surface type, lighted (bool), reservation required (bool), hours

### 16. Urgent Care / ER Wait Times
- **What:** Real-time or estimated wait times at ERs and urgent cares
- **Free APIs / Feeds:**
  - CMS Hospital Compare API — free, includes hospital metadata but NOT real-time waits
  - Individual hospital systems publish wait times on their websites (highly fragmented)
  - ProPublica Urgent Care dataset — static, research-grade
- **Browsing fallback:** Primary method. Hospital system homepages display live wait times (e.g., Ascension, HCA, Baylor Scott & White). Fragmented but high-value.
- **Schema needs:** Facility name, geocode, facility type (ER/urgent care/freestanding ER), wait minutes, timestamp, source URL

### 17. Air Quality / Pollen
- **What:** Hyperlocal AQI, pollen counts, allergen forecasts
- **Free APIs / Feeds:**
  - EPA AirNow API — **free, official**, real-time AQI by reporting area and monitor station geocodes
  - OpenAQ API — **free, open-source**, global air quality from government monitors
  - PurpleAir API — **free tier (limited)**, crowdsourced hyperlocal sensors with exact geocodes
  - Pollen.com API (Copernicus / IQAir) — some free tiers; Tomorrow.io pollen endpoint (free tier)
  - Ambee Pollen API — freemium, 100 calls/day free
- **Schema needs:** Station/sensor geocode, AQI value, pollutant breakdown, pollen type + count, timestamp

### 18. Crime / Safety Heat Maps
- **What:** Recent incident reports geocoded for local awareness
- **Free APIs / Feeds:**
  - City open data portals — Austin, Chicago, NYC, LA, etc. all publish crime incident CSVs/APIs (free, usually Socrata-powered)
  - CrimeMapping.com — aggregates police data, no API but structured pages
  - SpotCrime API — freemium
  - FBI UCR / NIBRS — annual aggregate, not real-time, not geocoded to address level
- **Browsing fallback:** CrimeMapping.com, local PD blotter pages
- **Schema needs:** Incident type, geocode, datetime, severity, source agency, report ID

### 19. Little Free Libraries / Tool Libraries / Sharing Economies
- **What:** Community book exchanges, tool lending libraries, sharing sheds
- **Free APIs / Feeds:**
  - LittleFreeLibrary.org — official map with charter numbers; no public API but structured map data
  - OpenStreetMap — `amenity=public_bookcase` via Overpass (free)
  - LocalTools.org / tool library directories — small, fragmented
- **Browsing fallback:** LittleFreeLibrary.org map, local Buy Nothing groups
- **Schema needs:** Name/ID, geocode, type (books/tools/seeds/other), notes, photo URL

### 20. Coworking / Study Spots
- **What:** Cafes with outlets, libraries with quiet rooms, day-pass coworking
- **Free APIs / Feeds:**
  - OpenStreetMap — `amenity=coworking_space` via Overpass (free)
  - Coworker.com — directory, no free API
  - Library system websites — branch hours and amenities
  - Workfrom.co — crowdsourced cafe-as-workspace reviews, limited API
- **Browsing fallback:** "Best cafes to work from in [city]" articles, Google Maps reviews mentioning outlets/wifi
- **Schema needs:** Name, geocode, type (cafe/library/coworking), wifi (bool), outlets (bool), noise level, day pass cost, hours

### 21. Water Fountains / Bottle Refill Stations
- **What:** Drinking water access points, especially for outdoor activity
- **Free APIs / Feeds:**
  - OpenStreetMap — `amenity=drinking_water` via Overpass (free) — **best source, excellent coverage**
  - WeTap — crowdsourced water fountain map, limited API
- **Schema needs:** Geocode, type (fountain/bottle refill/both), indoor/outdoor, functional (bool)

### 22. Thrift Stores / Buy Nothing / Secondhand
- **What:** Thrift shops, consignment, Buy Nothing group coverage areas
- **Free APIs / Feeds:**
  - OpenStreetMap — `shop=charity`, `shop=second_hand` via Overpass (free)
  - Yelp Fusion — category filter for thrift stores (free tier)
  - ThriftShopper — directory, no API
  - Buy Nothing Project — Facebook Group based, mapped by neighborhood; no API
- **Browsing fallback:** Buy Nothing Facebook groups, local thrift store hours pages
- **Schema needs:** Name, geocode, type (thrift/consignment/buy-nothing zone), hours, accepts donations (bool)

### 23. Community Classes
- **What:** Free or low-cost classes — rec centers, community colleges, nonprofits
- **Free APIs / Feeds:**
  - City Parks & Rec program catalogs — often published as PDFs or structured web pages
  - Community college continuing ed catalogs — browsable
  - Coursera/Skillshare — not local, skip
  - Library event calendars — often include classes (iCal/RSS)
- **Browsing fallback:** Primary method. City rec center program guides, library calendars, nonprofit event pages.
- **Schema needs:** Class name, geocode, datetime/recurrence, cost, category (fitness/art/tech/language), age range, registration URL

### 24. Childcare / Drop-In Daycare
- **What:** Licensed daycare availability, drop-in options
- **Free APIs / Feeds:**
  - State licensing databases — Texas HHS publishes licensed childcare facility data (free, downloadable CSV)
  - ChildCareAware.org — locator, no API
  - Care.com — no free API
- **Browsing fallback:** Care.com, Winnie.com, state licensing search portals
- **Schema needs:** Facility name, geocode, type (center/home/drop-in), ages served, hours, cost range, license status, vacancy (if obtainable)

### 25. Public Transit Disruptions
- **What:** Real-time service alerts geocoded to affected stops/routes
- **Free APIs / Feeds:**
  - GTFS-RT (General Transit Feed Specification Realtime) — **free, standardized**, published by most U.S. transit agencies. CapMetro (Austin) publishes GTFS-RT feeds.
  - CapMetro API — free, includes real-time vehicle positions and alerts
  - TransitLand API — **free**, aggregates GTFS feeds from hundreds of agencies
  - OpenMobilityData — GTFS feed archive
- **Schema needs:** Route ID, stop geocodes, alert type (delay/detour/suspension), severity, start/end datetime, description

---

## Collection Method Legend

| Method | Cost | Best For |
|---|---|---|
| **Open API (free key)** | Free | AQI, EV charging, transit, jobs, DOE data |
| **OpenStreetMap / Overpass** | Free | Parking, restrooms, water, courts, dog parks, Wi-Fi |
| **City open data portals** | Free | Crime, parking, events, permits, childcare licensing |
| **Freemium API** | Free–$10/mo | Gas prices, pollen, pet venues, coworking |
| **SpiritPool / EDN browsing** | Human time | Happy hours, meal deals, garage sales, ER wait times, Facebook events, housing, community classes |

---

## Priority Tiers

### Tier 1 — High demand, good free data available
- Free / community events
- EV charging stations
- Public transit disruptions
- Air quality / pollen
- Crime / safety heat maps
- Gas prices

### Tier 2 — High demand, mostly requires browsing
- Happy hours
- Meal deals (already planned)
- Urgent care wait times
- Garage sales / estate sales
- Open houses / rent drops

### Tier 3 — Moderate demand, mostly free via OSM
- Public restrooms
- Water fountains
- Free parking
- Pet-friendly spaces
- Pickup sports courts
- Free Wi-Fi
- Little Free Libraries

### Tier 4 — Niche but valuable
- Coworking / study spots
- Thrift stores / Buy Nothing
- Community classes
- Childcare / drop-in daycare
- Blood drives
- Free food / food banks

---

## Next Steps

- [ ] Define a universal POI schema that all categories share (name, geocode, category, source, freshness timestamp, source URL)
- [ ] Audit Austin-specific open data portal for quick wins
- [ ] Build OpenStreetMap Overpass query templates for all Tier 3 categories
- [ ] Identify which Tier 1 APIs need key registration and register
- [ ] Design SpiritPool browsing task templates for Tier 2 categories
- [ ] Determine refresh cadence per category (real-time vs daily vs weekly vs quarterly)
