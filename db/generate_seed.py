"""Deterministic generator for db/seed.sql — the curated travel dataset.

Run:  python3 db/generate_seed.py    (or: make seed)

Keeps the committed seed.sql reproducible and BROAD enough that a presenter can
go off-script: ~50 destinations across every region, flights from 13 major
origins (both directions, several dates), and hotels/attractions for every
place. The 20 headline cities are hand-curated (real names); the long tail is
generated from templates with a fixed RNG seed so it's plausible and stable.
"""

import random
from pathlib import Path

RNG = random.Random(42)

# ── destinations ─────────────────────────────────────────────────────────────
# region drives rough flight distance/price; budget (USD/day) scales hotel prices.
def D(city, country, region, code, season, budget, tags, summary):
    return dict(city=city, country=country, region=region, code=code, season=season,
                budget=budget, tags=tags, summary=summary)

DESTINATIONS = [
    # ── Asia ──
    D("Tokyo", "Japan", "Asia", "HND", "Mar–May & Oct–Nov", 190, "food,culture,city,nightlife,shopping",
      "A hyper-modern metropolis of neon districts, Michelin-dense dining, serene shrines, and endless neighborhoods to wander."),
    D("Kyoto", "Japan", "Asia", "KIX", "Mar–Apr & Nov", 165, "culture,temples,gardens,history,food",
      "Japan's old imperial capital — thousands of temples and shrines, geisha districts, and bamboo groves wrapped in tradition."),
    D("Bangkok", "Thailand", "Asia", "BKK", "Nov–Feb (cool, dry)", 70, "food,culture,temples,nightlife,budget",
      "A fast, fragrant capital of golden temples, canal markets, rooftop bars, and the best street food on earth."),
    D("Singapore", "Singapore", "Asia", "SIN", "Feb–Apr", 175, "food,city,family,shopping,gardens",
      "A gleaming garden-city of hawker feasts, futuristic parks, and spotless efficiency where every cuisine converges."),
    D("Bali", "Indonesia", "Asia", "DPS", "Apr–Oct (dry)", 95, "beach,wellness,nature,budget,surf",
      "Rice terraces, temple gates, surf breaks, and yoga retreats across an island built for slow, sun-warmed days."),
    D("Hong Kong", "China", "Asia", "HKG", "Oct–Dec", 165, "food,city,shopping,skyline,hiking",
      "A vertical city where dim sum, neon harbors, hillside trails, and dense street markets collide."),
    D("Seoul", "South Korea", "Asia", "ICN", "Apr–Jun & Sep–Nov", 140, "food,culture,shopping,nightlife,tech",
      "Palaces beside skyscrapers — Korean BBQ, all-night neighborhoods, K-beauty, and mountain temples on the metro line."),
    D("Hanoi", "Vietnam", "Asia", "HAN", "Oct–Apr", 55, "food,culture,history,budget,coffee",
      "A characterful old capital of lakeside cafes, motorbike-buzzing lanes, and some of Asia's most rewarding street food."),
    D("Kathmandu", "Nepal", "Asia", "KTM", "Oct–Nov & Mar–Apr", 45, "adventure,culture,temples,hiking,budget",
      "The gateway to the Himalaya — medieval temple squares, prayer flags, and the launchpad for Everest and Annapurna treks."),
    D("Mumbai", "India", "Asia", "BOM", "Nov–Feb", 75, "food,culture,city,history,budget",
      "India's high-energy coastal megacity — colonial architecture, Bollywood, seaside promenades, and legendary street eats."),
    # ── Middle East ──
    D("Dubai", "United Arab Emirates", "Middle East", "DXB", "Nov–Mar", 220, "luxury,shopping,desert,beach,city",
      "A desert boomtown of record-breaking towers, gold souks, dune safaris, and beach-club glamour."),
    # ── Europe ──
    D("Paris", "France", "Europe", "CDG", "Apr–Jun & Sep–Oct", 210, "art,food,romance,history,museums",
      "The archetypal European capital: world-class museums, cafe culture, grand boulevards, and food worth crossing an ocean for."),
    D("Rome", "Italy", "Europe", "FCO", "Apr–Jun & Sep–Oct", 175, "history,food,art,architecture,ruins",
      "An open-air museum where ancient ruins, Baroque piazzas, and trattoria dinners share the same cobblestone streets."),
    D("Barcelona", "Spain", "Europe", "BCN", "May–Jun & Sep", 165, "beach,architecture,nightlife,food,art",
      "Gaudí's surreal architecture meets Mediterranean beaches, tapas bars, and a nightlife that runs until sunrise."),
    D("Madrid", "Spain", "Europe", "MAD", "Apr–Jun & Sep–Oct", 150, "art,food,nightlife,history,football",
      "Spain's sun-soaked capital — world-class art museums, late-night tapas crawls, grand plazas, and a football-mad soul."),
    D("Lisbon", "Portugal", "Europe", "LIS", "Mar–May & Sep–Oct", 130, "food,coast,history,budget,views",
      "Hills, tiled facades, and trams over the Tagus — Western Europe's most affordable capital, with seafood and soulful fado."),
    D("London", "United Kingdom", "Europe", "LHR", "May–Sep", 240, "history,museums,theatre,food,city",
      "A global capital of free world-class museums, West End theatre, historic pubs, and a food scene from every corner of the earth."),
    D("Amsterdam", "Netherlands", "Europe", "AMS", "Apr–May & Sep", 200, "art,canals,cycling,museums,nightlife",
      "A canal-ringed city of Golden Age museums, gabled houses, bike lanes everywhere, and an easygoing pace."),
    D("Reykjavik", "Iceland", "Europe", "KEF", "Jun–Aug & Sep–Mar (auroras)", 235, "nature,adventure,northern-lights,geothermal,roadtrip",
      "A tiny capital at the edge of the Arctic — the launchpad for waterfalls, geysers, glaciers, and the northern lights."),
    D("Prague", "Czech Republic", "Europe", "PRG", "Apr–Jun & Sep–Oct", 110, "history,architecture,beer,budget,romance",
      "A fairy-tale city of Gothic spires, a medieval astronomical clock, and the world's best-value beer halls."),
    D("Vienna", "Austria", "Europe", "VIE", "Apr–May & Sep–Oct", 165, "music,art,history,cafes,architecture",
      "Imperial palaces, coffeehouse culture, and a classical-music pedigree, all wrapped in grand Habsburg elegance."),
    D("Athens", "Greece", "Europe", "ATH", "Apr–Jun & Sep–Oct", 150, "history,ruins,food,culture,nightlife",
      "The cradle of Western civilization — the Acropolis over a buzzing modern capital of tavernas, markets, and nightlife."),
    D("Santorini", "Greece", "Europe", "JTR", "May–Jun & Sep", 210, "beach,romance,views,wine,luxury",
      "Whitewashed villages tumbling down volcanic cliffs above a caldera — the definitive Aegean sunset."),
    D("Mykonos", "Greece", "Europe", "JMK", "May–Jun & Sep", 240, "beach,nightlife,luxury,romance,views",
      "A Cycladic postcard of whitewashed lanes and windmills by day, a world-famous party island by night."),
    D("Istanbul", "Turkey", "Europe", "IST", "Apr–May & Sep–Oct", 95, "history,food,culture,markets,mosques",
      "Where Europe meets Asia across the Bosphorus — imperial mosques, sprawling bazaars, and a legendary food culture."),
    D("Copenhagen", "Denmark", "Europe", "CPH", "May–Aug", 215, "design,food,cycling,hygge,harbor",
      "A design-forward harbor capital of New Nordic dining, cycle lanes, colorful quays, and effortless cool."),
    D("Zurich", "Switzerland", "Europe", "ZRH", "Jun–Sep (Dec–Mar ski)", 260, "nature,alps,luxury,hiking,lakes",
      "A lakeside gateway to the Alps — pristine, walkable, and an hour from world-class hiking and skiing."),
    D("Dubrovnik", "Croatia", "Europe", "DBV", "May–Jun & Sep", 160, "beach,history,views,coast,walls",
      "A honey-stone walled city on the Adriatic — marble streets, sea-cliff swims, and Game of Thrones fame."),
    D("Edinburgh", "United Kingdom", "Europe", "EDI", "May–Sep", 165, "history,castles,festivals,whisky,walks",
      "A dramatic capital of a clifftop castle, medieval closes, and August's world-famous Fringe festival."),
    # ── Africa ──
    D("Cape Town", "South Africa", "Africa", "CPT", "Nov–Mar", 140, "nature,wine,beach,adventure,views",
      "Table Mountain over two oceans, penguin beaches, and the Cape Winelands an hour from the city center."),
    D("Marrakech", "Morocco", "Africa", "RAK", "Mar–May & Sep–Nov", 90, "culture,markets,desert,food,history",
      "A sensory maze of souks and riads, palm gardens and palaces, with the Atlas Mountains and Sahara on the doorstep."),
    D("Cairo", "Egypt", "Africa", "CAI", "Oct–Apr", 70, "history,ruins,culture,budget,desert",
      "The gateway to the Pyramids and the Nile — millennia of pharaonic history beside a chaotic, captivating megacity."),
    D("Nairobi", "Kenya", "Africa", "NBO", "Jun–Oct & Jan–Feb", 120, "safari,nature,wildlife,adventure",
      "The safari capital of East Africa — big-game parks minutes from downtown and a base for the Maasai Mara."),
    D("Zanzibar", "Tanzania", "Africa", "ZNZ", "Jun–Oct", 110, "beach,culture,history,diving,spice",
      "White-sand Indian Ocean beaches, dhow boats, and the labyrinthine, spice-scented alleys of Stone Town."),
    # ── North America ──
    D("New York City", "USA", "North America", "JFK", "Apr–Jun & Sep–Nov", 260, "city,food,culture,nightlife,museums",
      "The city that never sleeps — Broadway, world museums, every cuisine on earth, and a skyline in constant motion."),
    D("San Francisco", "USA", "North America", "SFO", "Sep–Nov", 240, "food,tech,nature,coast,city",
      "Fog-wrapped hills, the Golden Gate, a legendary food scene, and wine country and redwoods just up the road."),
    D("Los Angeles", "USA", "North America", "LAX", "Mar–May & Sep–Nov", 220, "beach,film,food,city,sun",
      "Endless sunshine, beach towns, Hollywood, and taco trucks — a sprawling, sun-soaked capital of pop culture."),
    D("Miami", "USA", "North America", "MIA", "Nov–Apr", 210, "beach,nightlife,food,art,sun",
      "Art Deco beaches, Latin flavor, and a nonstop nightlife scene where South Beach meets Little Havana."),
    D("Seattle", "USA", "North America", "SEA", "Jun–Sep", 200, "coffee,food,nature,water,tech",
      "Coffee, salmon, and snow-capped volcanoes — a laid-back Pacific Northwest city of markets, waterfront, and evergreen day hikes."),
    D("Atlanta", "USA", "North America", "ATL", "Mar–May & Sep–Nov", 160, "food,music,history,sports,city",
      "The capital of the New South — civil-rights history, a booming food and music scene, leafy neighborhoods, and Southern hospitality."),
    D("Honolulu", "USA", "North America", "HNL", "Apr–Jun & Sep–Nov", 250, "beach,surf,nature,family,sun",
      "Waikiki's surf and sand, volcanic hikes, and pristine snorkeling — the accessible heart of Hawaii."),
    D("Vancouver", "Canada", "North America", "YVR", "Jun–Sep", 190, "nature,food,city,mountains,coast",
      "Mountains meeting the sea — a green, outdoorsy city with world-class sushi, ski slopes, and seawall bike paths."),
    D("Mexico City", "Mexico", "North America", "MEX", "Mar–May & Oct–Nov", 110, "food,culture,history,budget,art",
      "A high-altitude megacity of world-ranked restaurants, Aztec ruins, muralist art, and leafy, walkable neighborhoods."),
    D("Cancún", "Mexico", "North America", "CUN", "Dec–Apr", 160, "beach,resort,nightlife,ruins,diving",
      "Turquoise Caribbean water and powder beaches, all-inclusive resorts, and Maya ruins along the Riviera Maya."),
    # ── Caribbean ──
    D("Havana", "Cuba", "Caribbean", "HAV", "Nov–Apr", 90, "culture,history,music,vintage,beach",
      "Vintage cars, crumbling grandeur, live son and salsa — a time-capsule capital brimming with rhythm and rum."),
    # ── South America ──
    D("Rio de Janeiro", "Brazil", "South America", "GIG", "Dec–Mar", 130, "beach,nature,nightlife,views,culture",
      "Christ the Redeemer over Copacabana and Ipanema — mountains, samba, and beach culture in one dramatic setting."),
    D("Buenos Aires", "Argentina", "South America", "EZE", "Sep–Nov & Mar–May", 100, "food,culture,tango,nightlife,architecture",
      "The Paris of South America — steak and Malbec, tango halls, grand boulevards, and a legendary nightlife."),
    D("Cusco", "Peru", "South America", "CUZ", "May–Sep (dry)", 90, "history,ruins,adventure,hiking,culture",
      "The Inca heartland at 3,400m — cobbled colonial streets and the gateway to Machu Picchu and the Sacred Valley."),
    D("Cartagena", "Colombia", "South America", "CTG", "Dec–Apr", 110, "beach,history,coast,nightlife,culture",
      "A walled Caribbean jewel of balconied colonial mansions, bougainvillea, and warm Colombian nights."),
    # ── Oceania ──
    D("Sydney", "Australia", "Oceania", "SYD", "Sep–Nov & Mar–May", 210, "beach,city,food,harbor,nature",
      "The Opera House and Harbour Bridge over a sparkling bay — surf beaches, coastal walks, and a buzzing food scene."),
    D("Queenstown", "New Zealand", "Oceania", "ZQN", "Dec–Feb & Jun–Aug (ski)", 185, "adventure,nature,skiing,hiking,lakes",
      "The adventure capital of the Southern Hemisphere: bungee, jet boats, and alpine trails ringing a glacial lake."),
    D("Auckland", "New Zealand", "Oceania", "AKL", "Dec–Mar", 175, "nature,coast,food,sailing,city",
      "The 'City of Sails' among harbors and volcanoes — a laid-back base for islands, wineries, and black-sand beaches."),
    D("Bora Bora", "French Polynesia", "Oceania", "PPT", "May–Oct (dry)", 480, "beach,luxury,romance,diving,honeymoon",
      "Overwater bungalows above an impossibly blue lagoon, ringed by a volcanic peak — the honeymoon archetype."),
    D("Fiji", "Fiji", "Oceania", "NAN", "May–Oct (dry)", 220, "beach,diving,resort,family,snorkeling",
      "Hundreds of palm-fringed islands, coral reefs, and famously warm hospitality across the South Pacific."),
]

# ── curated attractions: city -> [(name, category, cost, hours, description)] ──
CURATED_ATTRACTIONS = {
    "San Francisco": [
        ("Golden Gate Bridge", "Landmark", 0, 1.5, "Walk or bike across the iconic red suspension bridge over the bay."),
        ("Alcatraz Island", "History", 47, 3.0, "Ferry to the infamous former island prison in San Francisco Bay."),
        ("Fisherman's Wharf & Pier 39", "Neighborhood", 0, 2.0, "Barking sea lions, sourdough bowls, and bay views along the historic waterfront."),
        ("Ferry Building Marketplace", "Food", 25, 1.5, "Artisan food hall and farmers market on the Embarcadero."),
        ("Muir Woods", "Nature", 15, 4.0, "Towering old-growth redwoods a short drive across the Golden Gate."),
    ],
    "Seattle": [
        ("Pike Place Market", "Food", 20, 2.0, "The century-old public market — fishmongers, the original Starbucks, and endless stalls."),
        ("Space Needle", "Viewpoint", 35, 1.5, "The 1962 World's Fair tower with a revolving glass floor and skyline views."),
        ("Chihuly Garden and Glass", "Museum", 35, 1.5, "Dazzling blown-glass sculptures indoors and in a garden beneath the Space Needle."),
        ("Museum of Pop Culture", "Museum", 32, 2.0, "Music, sci-fi, and pop-culture exhibits in a swooping Frank Gehry building."),
        ("Mount Rainier Day Trip", "Day Trip", 90, 8.0, "Wildflower meadows and glaciers on a full-day trip to the volcano."),
    ],
    "Atlanta": [
        ("Georgia Aquarium", "Family", 45, 3.0, "One of the world's largest aquariums — whale sharks, beluga whales, and manta rays."),
        ("World of Coca-Cola", "Museum", 20, 1.5, "The story of the iconic soda, ending in a global tasting room."),
        ("Martin Luther King Jr. Historic Site", "History", 0, 2.0, "The birth home, church, and memorial of the civil-rights leader."),
        ("Atlanta BeltLine & Ponce City Market", "Neighborhood", 0, 2.5, "A former rail corridor turned trail, linking parks, murals, and a landmark food hall."),
        ("Piedmont Park", "Park", 0, 1.5, "The city's green heart with skyline views and weekend markets."),
    ],
    "Madrid": [
        ("Museo del Prado", "Museum", 15, 2.5, "One of the world's great art museums — Velázquez, Goya, and the Spanish masters."),
        ("Royal Palace of Madrid", "Landmark", 15, 2.0, "The lavish official residence of the Spanish crown, with opulent state rooms."),
        ("Retiro Park", "Park", 0, 1.5, "Madrid's elegant green heart — rowboats on the lake and the glass Crystal Palace."),
        ("Mercado de San Miguel", "Food", 25, 1.5, "A historic iron-and-glass market hall for tapas, jamón, and vermouth."),
        ("Santiago Bernabéu Stadium Tour", "Sports", 30, 2.0, "Behind the scenes at Real Madrid's legendary football cathedral."),
    ],
    "Tokyo": [
        ("Senso-ji Temple", "Landmark", 0, 1.5, "Tokyo's oldest temple, approached through the lantern-lit Nakamise shopping street."),
        ("teamLab Planets", "Museum", 32, 2.0, "Immersive digital-art installation you walk through barefoot, often ankle-deep in water."),
        ("Tsukiji Outer Market", "Food", 25, 2.0, "Warren of stalls serving the freshest sushi, tamagoyaki, and street snacks in the city."),
        ("Shibuya Sky", "Viewpoint", 20, 1.5, "Open-air rooftop deck above the world's busiest crossing, best at sunset."),
        ("Meiji Jingu", "Nature", 0, 1.5, "A forest shrine in the heart of the city, a calm counterpoint to Harajuku next door."),
    ],
    "Kyoto": [
        ("Fushimi Inari Taisha", "Landmark", 0, 2.5, "Thousands of vermilion torii gates winding up a sacred mountainside."),
        ("Arashiyama Bamboo Grove", "Nature", 0, 1.0, "A towering green corridor of bamboo, magical in early-morning light."),
        ("Kinkaku-ji", "Landmark", 5, 1.0, "The Golden Pavilion mirrored in its reflecting pond — Kyoto's iconic image."),
        ("Gion District", "Culture", 0, 2.0, "Historic geisha quarter of wooden machiya, teahouses, and lantern-lit lanes."),
        ("Nishiki Market", "Food", 20, 1.5, "The 'Kyoto kitchen' — five blocks of pickles, sweets, and skewers."),
    ],
    "Bangkok": [
        ("Grand Palace & Wat Phra Kaew", "Landmark", 15, 2.5, "The dazzling former royal palace and the Emerald Buddha temple."),
        ("Wat Arun", "Landmark", 3, 1.0, "The porcelain-studded Temple of Dawn on the Chao Phraya riverbank."),
        ("Chatuchak Weekend Market", "Shopping", 0, 3.0, "One of the world's largest markets — 15,000 stalls of everything imaginable."),
        ("Chao Phraya Dinner Cruise", "Experience", 40, 2.5, "Glide past floodlit temples and skyscrapers over dinner."),
        ("Chinatown Street Food Tour", "Food", 25, 3.0, "Yaowarat Road after dark: the planet's densest street-food strip."),
    ],
    "Singapore": [
        ("Gardens by the Bay", "Nature", 20, 2.5, "Futuristic Supertrees and cooled biodomes on the Marina Bay waterfront."),
        ("Marina Bay Sands SkyPark", "Viewpoint", 26, 1.5, "The observation deck atop the iconic three-tower hotel."),
        ("Hawker Centre Food Tour", "Food", 25, 2.5, "Michelin-starred street food at Maxwell and Lau Pa Sat for a few dollars a plate."),
        ("Sentosa Island", "Experience", 40, 4.0, "Beaches, cable cars, and theme parks on a resort island minutes from downtown."),
        ("Chinatown & Little India", "Neighborhood", 0, 2.5, "Temples, spice shops, and heritage shophouses across two vivid quarters."),
    ],
    "Bali": [
        ("Tegallalang Rice Terraces", "Nature", 5, 1.5, "Emerald stepped paddies carved into the hills north of Ubud."),
        ("Uluwatu Temple", "Landmark", 5, 2.0, "Clifftop sea temple with a fiery sunset Kecak dance."),
        ("Sacred Monkey Forest", "Nature", 6, 1.5, "Jungle sanctuary of mossy temples and long-tailed macaques in Ubud."),
        ("Sekumpul Waterfall", "Nature", 10, 4.0, "Bali's tallest falls, reached by a jungle trek in the north."),
        ("Seminyak Beach", "Beach", 0, 2.5, "Surf, sunset beach clubs, and the island's best boutique shopping."),
    ],
    "Paris": [
        ("Louvre Museum", "Museum", 22, 3.0, "The world's largest art museum, from the Mona Lisa to ancient antiquities."),
        ("Eiffel Tower", "Landmark", 29, 2.0, "Climb or lift up the iron lattice for the definitive Paris panorama."),
        ("Musée d'Orsay", "Museum", 16, 2.5, "Impressionist masterpieces inside a grand converted railway station."),
        ("Montmartre & Sacré-Cœur", "Neighborhood", 0, 2.5, "Hilltop artists' quarter crowned by a white basilica over the rooftops."),
        ("Seine River Cruise", "Experience", 18, 1.0, "Glide past Notre-Dame and the bridges, especially lovely after dark."),
    ],
    "Athens": [
        ("Acropolis & Parthenon", "Landmark", 20, 2.5, "The 5th-century-BC citadel crowned by the Parthenon, over the whole city."),
        ("Acropolis Museum", "Museum", 15, 2.0, "A glass-floored modern museum of the Acropolis' sculptures and finds."),
        ("Plaka & Monastiraki", "Neighborhood", 0, 2.5, "Old-town lanes of tavernas, markets, and Roman ruins beneath the Acropolis."),
        ("Ancient Agora", "History", 10, 1.5, "The heart of classical Athens — the Temple of Hephaestus and the Stoa."),
        ("Cape Sounion Sunset", "Day Trip", 45, 4.0, "The clifftop Temple of Poseidon at sunset, an hour down the coast."),
    ],
    "Santorini": [
        ("Oia Sunset", "Viewpoint", 0, 1.5, "The world-famous sunset over the caldera from the village of Oia."),
        ("Caldera Catamaran Cruise", "Experience", 95, 5.0, "Sail the volcanic caldera with hot springs, snorkeling, and dinner."),
        ("Ancient Akrotiri", "History", 12, 1.5, "A remarkably preserved Bronze-Age town buried by a volcanic eruption."),
        ("Santo Wines Tasting", "Food", 35, 2.0, "Assyrtiko tastings on a caldera-edge terrace at the island's co-op winery."),
        ("Red Beach", "Beach", 0, 2.0, "Dramatic red volcanic cliffs and sand near Akrotiri."),
    ],
    "Mykonos": [
        ("Little Venice", "Neighborhood", 0, 1.5, "Balconied houses right on the water, best at sunset with a cocktail."),
        ("Windmills of Kato Mili", "Landmark", 0, 1.0, "The iconic 16th-century windmills above Mykonos Town."),
        ("Delos Day Trip", "Day Trip", 50, 4.0, "Boat to the sacred archaeological island, the birthplace of Apollo."),
        ("Paradise Beach", "Beach", 0, 3.0, "The island's legendary beach-club and party strip."),
        ("Mykonos Town (Chora)", "Neighborhood", 0, 2.0, "A whitewashed maze of boutiques, chapels, and bougainvillea."),
    ],
    "Rome": [
        ("Colosseum", "Landmark", 18, 2.0, "The vast ancient amphitheater at the heart of Imperial Rome."),
        ("Vatican Museums & Sistine Chapel", "Museum", 20, 3.0, "Miles of art ending under Michelangelo's ceiling."),
        ("Pantheon", "Landmark", 5, 1.0, "A 2,000-year-old temple with the world's largest unreinforced concrete dome."),
        ("Trastevere", "Neighborhood", 0, 2.5, "Cobbled, ivy-draped district best explored over a long trattoria dinner."),
        ("Trevi Fountain", "Landmark", 0, 0.5, "Baroque marble spectacle — toss a coin to ensure your return."),
    ],
    "Barcelona": [
        ("Sagrada Família", "Landmark", 26, 1.5, "Gaudí's still-unfinished basilica, an otherworldly forest of stone and light."),
        ("Park Güell", "Park", 10, 1.5, "Mosaic terraces and whimsical pavilions overlooking the city."),
        ("La Boqueria Market", "Food", 20, 1.0, "Kaleidoscopic food hall off La Rambla — jamón, seafood, fresh juices."),
        ("Gothic Quarter", "Neighborhood", 0, 2.0, "Medieval maze of narrow lanes, hidden squares, and Roman ruins."),
        ("Barceloneta Beach", "Beach", 0, 2.0, "City-edge sand and chiringuitos a short metro ride from the center."),
    ],
    "Lisbon": [
        ("Belém Tower & Jerónimos", "Landmark", 15, 2.0, "Manueline masterpieces from Portugal's Age of Discovery."),
        ("Tram 28", "Experience", 3, 1.0, "Vintage yellow tram rattling through Alfama's steepest, prettiest streets."),
        ("Time Out Market", "Food", 22, 1.5, "Portugal's best chefs and pastéis de nata under one roof."),
        ("São Jorge Castle", "Landmark", 15, 1.5, "Moorish hilltop fortress with the widest views over the Tagus."),
        ("Sintra Day Trip", "Day Trip", 25, 5.0, "Fairytale palaces in misty hills, 40 minutes by train from the city."),
    ],
    "London": [
        ("British Museum", "Museum", 0, 3.0, "Free encyclopedic collection from the Rosetta Stone to the Parthenon marbles."),
        ("Tower of London", "Landmark", 34, 2.5, "A thousand years of history, the Crown Jewels, and the Beefeaters."),
        ("Borough Market", "Food", 20, 1.5, "London's oldest food market — artisan producers and global street food."),
        ("West End Show", "Experience", 90, 3.0, "A world-class musical or play in the Theatreland heart of the city."),
        ("Hyde Park & Kensington", "Park", 0, 2.0, "Royal parkland, the Serpentine, and palace gardens in the city center."),
    ],
    "Amsterdam": [
        ("Rijksmuseum", "Museum", 22, 2.5, "Dutch Golden Age masters — Rembrandt's Night Watch and Vermeer."),
        ("Anne Frank House", "History", 16, 1.5, "The moving canal-house museum in the secret annex (book well ahead)."),
        ("Canal Cruise", "Experience", 18, 1.0, "Glide the UNESCO canal ring past gabled 17th-century houses."),
        ("Van Gogh Museum", "Museum", 20, 2.0, "The world's largest collection of the artist's work."),
        ("Jordaan District", "Neighborhood", 0, 2.0, "Charming canals, indie boutiques, brown cafes, and hidden courtyards."),
    ],
    "Reykjavik": [
        ("Golden Circle", "Day Trip", 90, 8.0, "Geysir, Gullfoss waterfall, and the continental rift at Þingvellir in one loop."),
        ("Blue Lagoon", "Experience", 75, 3.0, "Milky geothermal spa set in a black-lava field near the airport."),
        ("Northern Lights Tour", "Experience", 65, 4.0, "Evening chase for the aurora away from city lights (Sep–Mar)."),
        ("Hallgrímskirkja", "Landmark", 12, 1.0, "Concrete expressionist church with an elevator to a city-and-sea view."),
        ("South Coast Waterfalls", "Nature", 110, 10.0, "Seljalandsfoss, Skógafoss, and black-sand Reynisfjara down Route 1."),
    ],
    "Istanbul": [
        ("Hagia Sophia", "Landmark", 25, 1.5, "A 1,500-year-old marvel that has been church, mosque, and museum."),
        ("Blue Mosque", "Landmark", 0, 1.0, "The six-minaret imperial mosque with its cascade of blue-tiled domes."),
        ("Topkapı Palace", "History", 30, 2.5, "The opulent Ottoman sultans' palace overlooking the Bosphorus."),
        ("Grand Bazaar", "Shopping", 0, 2.0, "One of the world's oldest covered markets — 4,000 shops of carpets and gold."),
        ("Bosphorus Cruise", "Experience", 25, 2.0, "Sail the strait between two continents past palaces and fortresses."),
    ],
    "Cape Town": [
        ("Table Mountain Cableway", "Nature", 24, 2.5, "Rotating cable car to a flat-topped summit above the city and sea."),
        ("Robben Island", "History", 34, 4.0, "Ferry to the prison where Nelson Mandela was held, led by former inmates."),
        ("Cape of Good Hope", "Nature", 20, 5.0, "Dramatic headland drive to the southwestern tip of Africa."),
        ("Boulders Beach Penguins", "Nature", 12, 1.5, "Boardwalk among a colony of African penguins on a sheltered cove."),
        ("Cape Winelands Tour", "Food", 70, 6.0, "Stellenbosch and Franschhoek estates for tastings and long lunches."),
    ],
    "Marrakech": [
        ("Jemaa el-Fnaa", "Landmark", 0, 2.0, "The pulsing main square — snake charmers, food stalls, and storytellers at dusk."),
        ("Bahia Palace", "History", 10, 1.5, "A 19th-century palace of carved cedar, zellige tile, and tranquil courtyards."),
        ("Majorelle Garden", "Nature", 15, 1.5, "The cobalt-blue garden villa restored by Yves Saint Laurent."),
        ("Souks of the Medina", "Shopping", 0, 2.5, "A labyrinth of stalls for lanterns, leather, spices, and rugs."),
        ("Atlas Mountains Day Trip", "Day Trip", 60, 8.0, "Berber villages, valleys, and waterfalls under snow-capped peaks."),
    ],
    "Mexico City": [
        ("Teotihuacán Pyramids", "History", 30, 5.0, "Climb the vast Sun and Moon pyramids of a pre-Aztec city an hour away."),
        ("Frida Kahlo Museum", "Museum", 15, 1.5, "The cobalt-blue Casa Azul where the painter lived and worked."),
        ("Centro Histórico", "Neighborhood", 0, 3.0, "Zócalo square, the Metropolitan Cathedral, and Diego Rivera murals."),
        ("Xochimilco Trajineras", "Experience", 25, 3.0, "Float the ancient canals on painted boats with food and mariachi."),
        ("Mercado de San Juan", "Food", 20, 1.5, "Gourmet market for tacos, exotic ingredients, and street-food tastings."),
    ],
    "New York City": [
        ("Metropolitan Museum of Art", "Museum", 30, 3.0, "Encyclopedic collection on Central Park's edge — 5,000 years of art."),
        ("Statue of Liberty & Ellis Island", "Landmark", 25, 4.0, "Harbor ferry to Liberty Island and the immigration museum."),
        ("Top of the Rock", "Viewpoint", 40, 1.5, "Observation deck with the classic Empire State–in-frame skyline shot."),
        ("High Line & Chelsea Market", "Neighborhood", 0, 2.5, "Elevated park on old rail tracks leading into a landmark food hall."),
        ("Broadway Show", "Experience", 120, 3.0, "A marquee musical or play in the Theater District."),
    ],
    "Sydney": [
        ("Sydney Opera House Tour", "Landmark", 43, 1.5, "Behind the sails of the world's most famous performing-arts venue."),
        ("Sydney Harbour Bridge Climb", "Adventure", 240, 3.5, "Scale the arch for a 360° view over the harbor and city."),
        ("Bondi to Coogee Coastal Walk", "Nature", 0, 3.0, "A cliff-top path past beaches, rock pools, and surf breaks."),
        ("Taronga Zoo", "Nature", 40, 3.0, "Australian wildlife with a ferry ride and skyline backdrop."),
        ("The Rocks Markets", "Shopping", 0, 2.0, "Weekend stalls and history in the city's oldest cobbled quarter."),
    ],
    "Rio de Janeiro": [
        ("Christ the Redeemer", "Landmark", 30, 2.5, "The mountaintop icon over the city, reached by cog train through the forest."),
        ("Sugarloaf Cable Car", "Nature", 25, 2.0, "Two-stage cable car to a granite peak above Guanabara Bay."),
        ("Copacabana & Ipanema", "Beach", 0, 3.0, "The world's most famous beaches, side by side."),
        ("Selarón Steps", "Landmark", 0, 1.0, "A mosaic staircase of tiles from around the world in Lapa."),
        ("Tijuca Forest Hike", "Nature", 20, 4.0, "Trails and waterfalls in the world's largest urban rainforest."),
    ],
}

# ── curated hotels: city -> [(name, area, stars, nightly_price)] ──────────────
CURATED_HOTELS = {
    "San Francisco": [("The Ritz-Carlton San Francisco", "Nob Hill", 5, 620), ("Hotel Zephyr", "Fisherman's Wharf", 4, 290),
                      ("Hotel Zeppelin", "Union Square", 3, 210), ("HI San Francisco Downtown", "Union Square", 2, 70)],
    "Seattle": [("Fairmont Olympic Hotel", "Downtown", 5, 520), ("The Edgewater Hotel", "Waterfront", 4, 340),
                ("Hotel Ändra", "Belltown", 4, 240), ("Green Tortoise Hostel", "Pike Place", 2, 55)],
    "Atlanta": [("The St. Regis Atlanta", "Buckhead", 5, 480), ("Hotel Clermont", "Poncey-Highland", 4, 230),
                ("Glenn Hotel, Autograph Collection", "Downtown", 4, 190), ("Highland Inn", "Virginia-Highland", 2, 75)],
    "Madrid": [("The Madrid EDITION", "Centro", 5, 520), ("Only YOU Boutique Hotel", "Chueca", 4, 260),
               ("Hotel Regina", "Sol", 3, 150), ("The Hat Madrid", "La Latina", 2, 45)],
    "Tokyo": [("Park Hyatt Tokyo", "Shinjuku", 5, 620), ("Shibuya Stream Excel", "Shibuya", 4, 240),
              ("Hotel Gracery", "Shinjuku", 3, 145), ("UNPLAN Kagurazaka", "Kagurazaka", 2, 55)],
    "Kyoto": [("The Ritz-Carlton Kyoto", "Kamogawa", 5, 780), ("Hotel Kanra", "Shimogyo", 4, 320),
              ("Nazuna Kyoto Gosho", "Nakagyo", 4, 260), ("Piece Hostel Sanjo", "Nakagyo", 2, 60)],
    "Bangkok": [("Mandarin Oriental Bangkok", "Riverside", 5, 520), ("The Siam Heritage", "Silom", 4, 150),
                ("Ibis Styles Khaosan", "Banglamphu", 3, 60), ("Lub d Bangkok Silom", "Silom", 2, 25)],
    "Singapore": [("Marina Bay Sands", "Marina Bay", 5, 650), ("Parkroyal Collection Pickering", "Chinatown", 5, 380),
                  ("Hotel G Singapore", "Bugis", 4, 190), ("The Pod Capsule", "Beach Road", 2, 70)],
    "Bali": [("Four Seasons Sayan", "Ubud", 5, 850), ("Katamama", "Seminyak", 4, 300),
             ("Bisma Eight", "Ubud", 4, 180), ("The Farm Hostel", "Canggu", 2, 30)],
    "Paris": [("Le Meurice", "Tuileries", 5, 1100), ("Hôtel Fabric", "11th Arr.", 4, 260),
              ("Hôtel des Grands Boulevards", "2nd Arr.", 4, 300), ("Generator Paris", "10th Arr.", 2, 70)],
    "Rome": [("Hotel de Russie", "Piazza del Popolo", 5, 900), ("Hotel Santa Maria", "Trastevere", 4, 210),
             ("The Beehive", "Termini", 3, 110), ("The RomeHello", "Via Marsala", 2, 85)],
    "Athens": [("Hotel Grande Bretagne", "Syntagma", 5, 540), ("Coco-Mat Athens BC", "Kolonaki", 4, 240),
               ("360 Degrees", "Monastiraki", 4, 180), ("Athens Backpackers", "Makrigianni", 2, 40)],
    "Santorini": [("Katikies Santorini", "Oia", 5, 880), ("Grace Hotel Santorini", "Imerovigli", 5, 760),
                  ("Aroma Suites", "Fira", 4, 260), ("Caveland Hostel", "Karterados", 2, 60)],
    "Mykonos": [("Cavo Tagoo", "Mykonos Town", 5, 950), ("Myconian Kyma", "Mykonos Town", 5, 700),
                ("Semeli Hotel", "Mykonos Town", 4, 320), ("Paraga Beach Hostel", "Paraga", 2, 70)],
    "Barcelona": [("Hotel Arts Barcelona", "Port Olímpic", 5, 520), ("Yurbban Trafalgar", "El Born", 4, 240),
                  ("Casa Bonay", "Eixample", 4, 200), ("Generator Barcelona", "Gràcia", 2, 65)],
    "Lisbon": [("Bairro Alto Hotel", "Chiado", 5, 480), ("Memmo Alfama", "Alfama", 4, 260),
               ("The Lumiares", "Bairro Alto", 4, 230), ("Home Lisbon Hostel", "Baixa", 2, 45)],
    "London": [("The Savoy", "Covent Garden", 5, 720), ("The Hoxton Holborn", "Holborn", 4, 300),
               ("citizenM Tower of London", "City", 3, 210), ("YHA London Central", "Marylebone", 2, 55)],
    "Amsterdam": [("Waldorf Astoria Amsterdam", "Canal Belt", 5, 780), ("The Hoxton Amsterdam", "Herengracht", 4, 290),
                  ("Hotel V Nesplein", "Centrum", 4, 220), ("ClinkNOORD Hostel", "Noord", 2, 55)],
    "Reykjavik": [("The Reykjavik EDITION", "Old Harbour", 5, 560), ("Hótel Borg", "City Center", 4, 320),
                  ("Kvosin Downtown", "City Center", 4, 250), ("Kex Hostel", "Skúlagata", 2, 95)],
    "Istanbul": [("Four Seasons Sultanahmet", "Sultanahmet", 5, 560), ("Georges Hotel Galata", "Galata", 4, 240),
                 ("Sirkeci Mansion", "Sirkeci", 4, 180), ("Cheers Hostel", "Sultanahmet", 2, 35)],
    "Cape Town": [("The Silo Hotel", "V&A Waterfront", 5, 900), ("Gorgeous George", "City Center", 4, 240),
                  ("The Bay Hotel", "Camps Bay", 4, 300), ("Never at Home", "Green Point", 2, 40)],
    "Marrakech": [("La Mamounia", "Hivernage", 5, 650), ("Riad Kniza", "Medina", 4, 240),
                  ("Les Jardins de la Koutoubia", "Medina", 4, 190), ("Rodamon Riad Marrakech", "Medina", 2, 45)],
    "Mexico City": [("Las Alcobas", "Polanco", 5, 420), ("Hotel Carlota", "Cuauhtémoc", 4, 190),
                    ("Casa Decu", "Roma Norte", 4, 150), ("Casa Pepe Hostel", "Centro", 2, 35)],
    "New York City": [("The Ritz-Carlton NoMad", "NoMad", 5, 950), ("The Hoxton", "Williamsburg", 4, 340),
                      ("Pod Times Square", "Midtown", 3, 210), ("HI NYC Hostel", "Upper West Side", 2, 90)],
    "Sydney": [("Park Hyatt Sydney", "The Rocks", 5, 900), ("QT Sydney", "CBD", 4, 340),
               ("The Grantham", "Potts Point", 3, 220), ("Wake Up! Sydney", "Haymarket", 2, 55)],
    "Rio de Janeiro": [("Belmond Copacabana Palace", "Copacabana", 5, 700), ("Hotel Fasano Rio", "Ipanema", 5, 620),
                       ("Arena Copacabana Hotel", "Copacabana", 4, 160), ("Books Hostel", "Lapa", 2, 25)],
    "Queenstown": [("Eichardt's Private Hotel", "Lakefront", 5, 700), ("QT Queenstown", "Lakefront", 4, 320),
                   ("The Rees Hotel", "Sunshine Bay", 4, 260), ("Adventure Q2 Hostel", "Town Center", 2, 55)],
}

# ── curated events: city -> [(name, category, start_date, end_date, description)] ──
# The YEAR here (2026) is just a base — db.search_events re-bases it to the next
# upcoming occurrence at query time, so only the month/day matter (keep them in
# the event's real season). Flights work on any date, so no alignment is needed.
CURATED_EVENTS = {
    "San Francisco": [
        ("Hardly Strictly Bluegrass", "Music", "2026-10-02", "2026-10-04", "A free three-day roots-music festival in Golden Gate Park."),
        ("San Francisco Fleet Week", "Festival", "2026-10-08", "2026-10-13", "Blue Angels air shows and Navy ship tours over the bay."),
    ],
    "Seattle": [("Bumbershoot Arts Festival", "Festival", "2026-09-05", "2026-09-06", "Seattle's iconic music and arts festival at the Seattle Center.")],
    "Atlanta": [("Music Midtown", "Music", "2026-09-19", "2026-09-20", "A major two-day music festival in Piedmont Park.")],
    "Madrid": [("Festival de Otoño (Autumn Festival)", "Culture", "2026-10-01", "2026-10-25", "Madrid's flagship performing-arts festival across the city's theatres.")],
    "Auckland": [
        ("Pasifika Festival", "Festival", "2026-03-07", "2026-03-08", "The world's largest Pacific Island cultural festival — music, dance, and food at Western Springs."),
        ("Auckland Arts Festival", "Culture", "2026-03-11", "2026-03-29", "Three weeks of theatre, music, dance, and visual arts across the city."),
        ("Diwali Festival", "Culture", "2026-10-17", "2026-10-18", "A vibrant celebration of the festival of lights in the city center."),
    ],
    "Tokyo": [
        ("Tokyo Game Show", "Conference", "2026-09-24", "2026-09-27", "One of the world's biggest video-game expos, at Makuhari Messe."),
        ("Tokyo Jazz Festival", "Music", "2026-09-04", "2026-09-06", "Japan's flagship jazz festival with international headliners."),
    ],
    "Kyoto": [("Jidai Matsuri", "Culture", "2026-10-22", "2026-10-22", "The 'Festival of the Ages' — a grand costumed procession through Kyoto.")],
    "Bangkok": [("Vegetarian Festival", "Food", "2026-10-11", "2026-10-19", "Nine days of street food and ritual across the city's Chinatown.")],
    "Singapore": [
        ("Singapore Grand Prix", "Sports", "2026-09-18", "2026-09-20", "The Formula 1 night race through the Marina Bay street circuit."),
        ("Singapore Food Festival", "Food", "2026-06-12", "2026-06-21", "A citywide celebration of Singaporean cuisine and hawker culture."),
    ],
    "Barcelona": [("La Mercè Festival", "Festival", "2026-09-19", "2026-09-24", "Barcelona's biggest street party — human towers, fireworks, and concerts.")],
    "Athens": [
        ("Athens Epidaurus Festival", "Culture", "2026-06-01", "2026-08-31", "Greece's premier summer arts festival — ancient theatre, music, and dance."),
        ("Athens International Film Festival", "Culture", "2026-09-23", "2026-10-04", "Two weeks of world cinema across the city's historic theatres."),
    ],
    "Santorini": [("Santorini Jazz Festival", "Music", "2026-09-04", "2026-09-08", "Open-air jazz under the Aegean sky above the caldera.")],
    "Mykonos": [("XLSIOR Mykonos Festival", "Music", "2026-09-01", "2026-09-07", "A world-famous late-summer music festival on the party island.")],
    "Paris": [("Nuit Blanche", "Culture", "2026-10-03", "2026-10-03", "An all-night contemporary-art festival lighting up the whole city.")],
    "Rome": [("Rome Film Festival", "Culture", "2026-10-15", "2026-10-25", "Red-carpet premieres and screenings at the Auditorium Parco della Musica.")],
    "London": [("London Design Festival", "Culture", "2026-09-12", "2026-09-20", "Nine days of exhibitions and installations across the design capital.")],
    "Amsterdam": [("Amsterdam Dance Event", "Music", "2026-10-21", "2026-10-25", "The world's largest electronic-music conference and festival.")],
    "New York City": [("New York Film Festival", "Culture", "2026-09-25", "2026-10-11", "Lincoln Center's prestigious showcase of world cinema.")],
    "Rio de Janeiro": [("Rock in Rio", "Music", "2026-09-04", "2026-09-13", "One of the largest music festivals on earth, in the Cidade do Rock.")],
    "Sydney": [
        ("Sydney Marathon", "Sports", "2026-09-13", "2026-09-13", "A World Marathon Major finishing at the Opera House."),
        ("Vivid Sydney", "Festival", "2026-06-05", "2026-06-27", "A festival of light, music, and ideas across the harbor city."),
    ],
    "Cape Town": [("Cape Town Marathon", "Sports", "2026-10-18", "2026-10-18", "A fast, scenic World Marathon Major candidate race.")],
    "Reykjavik": [("Reykjavik Film Festival", "Culture", "2026-09-24", "2026-10-04", "Independent world cinema in Iceland's capital.")],
    "Istanbul": [("Istanbul Biennial", "Culture", "2026-09-12", "2026-11-08", "A major contemporary-art exhibition across historic venues.")],
    "Marrakech": [("Marrakech Film Festival", "Culture", "2026-12-04", "2026-12-12", "An international film festival with stars and screenings in the medina.")],
    "Mexico City": [("Día de los Muertos", "Culture", "2026-10-31", "2026-11-02", "The Day of the Dead — a huge parade and altars across the city.")],
    "Lisbon": [("Santos Populares", "Festival", "2026-06-12", "2026-06-13", "Sardine grills, street parties, and music through Alfama's alleys.")],
    "Vienna": [("Vienna Christmas Markets", "Festival", "2026-12-01", "2026-12-24", "Glühwein and craft stalls in the imperial city's squares.")],
    "Prague": [("Prague Christmas Markets", "Festival", "2026-12-01", "2026-12-24", "Old Town Square transformed with lights, crafts, and mulled wine.")],
}

# ── long-tail generators (plausible, deterministic) ──────────────────────────
AREA_POOL = ["City Center", "Old Town", "Waterfront", "Downtown", "Historic Quarter"]
EVENT_TEMPLATES = [
    ("{city} Food & Wine Festival", "Food"),
    ("{city} International Film Festival", "Culture"),
    ("{city} Summer Music Festival", "Music"),
    ("{city} Marathon", "Sports"),
]
EVENT_WINDOWS = [("03", 12, 3), ("06", 13, 2), ("09", 15, 3), ("10", 9, 4), ("12", 5, 2)]


def gen_events(city: str) -> list:
    r = random.Random("event:" + city)
    picks = r.sample(EVENT_TEMPLATES, 2)
    windows = r.sample(EVENT_WINDOWS, 2)
    out = []
    for (tmpl, cat), (mm, dd, span) in zip(picks, windows):
        start = f"2026-{mm}-{dd:02d}"
        end = f"2026-{mm}-{dd + span:02d}"
        name = tmpl.format(city=city)
        out.append((name, cat, start, end, f"A popular annual {cat.lower()} event drawing visitors to {city}."))
    return out


def gen_attractions(city: str) -> list:
    r = random.Random("attr:" + city)  # string seed → deterministic across runs
    return [
        (f"{city} Old Town Walking Tour", "Culture", r.choice([0, 10, 15, 20]), 2.5,
         f"A guided stroll through the historic heart of {city}, hitting the landmarks and hidden corners."),
        (f"{city} National Museum", "Museum", r.choice([10, 12, 16, 20]), 2.0,
         f"The city's flagship collection of {city}'s art, history, and culture."),
        (f"{city} Central Market & Food Tour", "Food", r.choice([20, 28, 35, 45]), 3.0,
         f"Taste your way through {city}'s market stalls and signature local dishes."),
        (f"{city} Panoramic Viewpoint", "Viewpoint", r.choice([0, 8, 12, 18]), 1.5,
         f"The classic lookout over {city} — best at sunset."),
        (f"{city} Nature Day Trip", "Day Trip", r.choice([45, 60, 80, 95]), 6.0,
         f"A full-day excursion to the scenery and villages around {city}."),
    ]


def gen_hotels(city: str, budget: int) -> list:
    r = random.Random("hotel:" + city)  # string seed → deterministic across runs

    def px(mult):  # price rounded to nearest 5, with light jitter
        return int(round(budget * mult * r.uniform(0.9, 1.12) / 5.0)) * 5

    return [
        (f"The {city} Grand", "City Center", 5, max(180, px(3.4))),
        (f"{city} Boutique Hotel", r.choice(AREA_POOL), 4, max(90, px(1.5))),
        (f"Hotel {city} Central", "Downtown", 3, max(55, px(0.85))),
        (f"{city} Backpackers", "City Center", 2, max(18, px(0.35))),
    ]


# ── flights ──────────────────────────────────────────────────────────────────
ORIGINS = [
    ("San Francisco", "SFO", "North America"), ("Los Angeles", "LAX", "North America"),
    ("New York City", "JFK", "North America"), ("Chicago", "ORD", "North America"),
    ("Seattle", "SEA", "North America"), ("Miami", "MIA", "North America"),
    ("Atlanta", "ATL", "North America"),  # hub — a common demoer hometown origin
    ("London", "LHR", "Europe"), ("Paris", "CDG", "Europe"), ("Frankfurt", "FRA", "Europe"),
    ("Madrid", "MAD", "Europe"),  # hub — a common demoer hometown origin
    ("Dubai", "DXB", "Middle East"), ("Singapore", "SIN", "Asia"),
    ("Hong Kong", "HKG", "Asia"), ("Sydney", "SYD", "Oceania"),
    ("Athens", "ATH", "Europe"),  # a hub too — enables domestic Athens ↔ island legs
]
# Extra point-to-point routes not covered by origin×destination (island hops).
EXTRA_ROUTES = [("Santorini", "JTR", "Europe", "Mykonos", "JMK", "Europe")]
# Short domestic hops priced/timed as island flights, not continental legs.
DOMESTIC_HOP_CODES = {"ATH", "JTR", "JMK"}
DOMESTIC_AIRLINES = [("Aegean Airlines", "A3"), ("Olympic Air", "OA"), ("Sky Express", "GQ")]
DEPART_DATES = ["2026-03-14", "2026-06-13", "2026-09-12", "2026-09-19", "2026-10-03", "2026-12-19"]
AIRLINES = [
    ("United", "UA"), ("Delta", "DL"), ("American", "AA"), ("British Airways", "BA"),
    ("ANA", "NH"), ("Japan Airlines", "JL"), ("Air France", "AF"), ("Lufthansa", "LH"),
    ("Emirates", "EK"), ("Qatar Airways", "QR"), ("Singapore Airlines", "SQ"), ("Iberia", "IB"),
    ("KLM", "KL"), ("Cathay Pacific", "CX"), ("Qantas", "QF"), ("Turkish Airlines", "TK"),
]
# cross-region base flight duration (minutes) keyed on the DESTINATION region.
REGION_DUR = {
    "North America": 320, "Central America": 340, "Caribbean": 360, "South America": 640,
    "Europe": 600, "Middle East": 760, "Africa": 720, "Asia": 780, "Oceania": 900,
}
REGION_PRICE_FACTOR = {
    "North America": 0.85, "Central America": 0.85, "Caribbean": 0.9, "South America": 1.2,
    "Europe": 1.0, "Middle East": 1.15, "Africa": 1.2, "Asia": 1.25, "Oceania": 1.45,
}


def q(s: str) -> str:
    return s.replace("'", "''")


def hhmm(mins: int) -> str:
    return f"{(mins // 60) % 24:02d}:{mins % 60:02d}"


def main() -> None:
    out: list[str] = []
    w = out.append

    w("/" + "*" * 78)
    w("   Travel Planner Database — generated by db/generate_seed.py")
    w("   Destinations, attractions, flights, hotels + per-conversation bookings.")
    w("   DB Server: PostgreSQL")
    w("*" * 78 + "/\n")

    w("DROP DATABASE IF EXISTS travel;")
    w("CREATE DATABASE travel;")
    w("\\c travel;\n")

    w("""CREATE TABLE destination (
    destination_id   INT PRIMARY KEY,
    city             VARCHAR(80)  NOT NULL,
    country          VARCHAR(80)  NOT NULL,
    region           VARCHAR(40)  NOT NULL,
    airport_code     VARCHAR(4)   NOT NULL,
    summary          TEXT,
    best_season      VARCHAR(60),
    avg_daily_budget INT,
    tags             VARCHAR(200)
);

CREATE TABLE attraction (
    attraction_id  INT PRIMARY KEY,
    destination_id INT NOT NULL REFERENCES destination(destination_id),
    name           VARCHAR(120) NOT NULL,
    category       VARCHAR(40),
    description    TEXT,
    typical_cost   NUMERIC(8,2),
    duration_hours NUMERIC(4,1)
);

CREATE TABLE flight (
    flight_id    INT PRIMARY KEY,
    airline      VARCHAR(60) NOT NULL,
    flight_no    VARCHAR(8)  NOT NULL,
    origin_city  VARCHAR(80) NOT NULL,
    origin_code  VARCHAR(4)  NOT NULL,
    dest_city    VARCHAR(80) NOT NULL,
    dest_code    VARCHAR(4)  NOT NULL,
    depart_date  DATE        NOT NULL,
    depart_time  VARCHAR(5)  NOT NULL,
    arrive_time  VARCHAR(5)  NOT NULL,
    duration_min INT         NOT NULL,
    stops        INT         NOT NULL,
    price        NUMERIC(8,2) NOT NULL,
    cabin        VARCHAR(20) NOT NULL
);

CREATE TABLE hotel (
    hotel_id       INT PRIMARY KEY,
    destination_id INT NOT NULL REFERENCES destination(destination_id),
    name           VARCHAR(120) NOT NULL,
    area           VARCHAR(80),
    stars          INT,
    rating         NUMERIC(2,1),
    nightly_price  NUMERIC(8,2)
);

-- Bookings are the demo's only mutable state. Each is scoped to a conversation
-- via account_key (the workflow ID), so back-to-back demos never collide and
-- nothing needs reseeding between runs.
CREATE TABLE booking (
    booking_id  INT PRIMARY KEY,
    account_key VARCHAR(120) NOT NULL,
    created_at  TIMESTAMP    NOT NULL DEFAULT now(),
    total       NUMERIC(10,2) NOT NULL,
    summary     TEXT
);

CREATE TABLE booking_line (
    booking_line_id INT PRIMARY KEY,
    booking_id      INT NOT NULL REFERENCES booking(booking_id),
    kind            VARCHAR(20) NOT NULL,
    ref_id          INT NOT NULL,
    title           VARCHAR(200),
    price           NUMERIC(8,2)
);

-- Events are the entry point of the "travel for an event" flow (FindEvents).
CREATE TABLE event (
    event_id       INT PRIMARY KEY,
    destination_id INT NOT NULL REFERENCES destination(destination_id),
    name           VARCHAR(160) NOT NULL,
    category       VARCHAR(40),
    start_date     DATE NOT NULL,
    end_date       DATE NOT NULL,
    description    TEXT
);

-- Invoices are the terminal action of the flight-booking flow (CreateInvoice),
-- scoped per-conversation like bookings.
CREATE TABLE invoice (
    invoice_id     INT PRIMARY KEY,
    account_key    VARCHAR(120) NOT NULL,
    created_at     TIMESTAMP NOT NULL DEFAULT now(),
    amount         NUMERIC(10,2) NOT NULL,
    flight_details TEXT
);

CREATE INDEX idx_attraction_dest ON attraction(destination_id);
CREATE INDEX idx_hotel_dest ON hotel(destination_id);
CREATE INDEX idx_flight_dest ON flight(dest_code);
CREATE INDEX idx_flight_origin ON flight(origin_code);
CREATE INDEX idx_booking_acct ON booking(account_key);
CREATE INDEX idx_event_dest ON event(destination_id);
CREATE INDEX idx_invoice_acct ON invoice(account_key);
""")

    # ── destinations ──
    w("\n-- destinations --")
    for i, d in enumerate(DESTINATIONS, 1):
        w(f"INSERT INTO destination (destination_id, city, country, region, airport_code, "
          f"summary, best_season, avg_daily_budget, tags) VALUES "
          f"({i}, '{q(d['city'])}', '{q(d['country'])}', '{q(d['region'])}', '{d['code']}', "
          f"'{q(d['summary'])}', '{q(d['season'])}', {d['budget']}, '{q(d['tags'])}');")

    # ── attractions (curated where available, else generated) ──
    w("\n-- attractions --")
    aid = 0
    for i, d in enumerate(DESTINATIONS, 1):
        rows = CURATED_ATTRACTIONS.get(d["city"]) or gen_attractions(d["city"])
        for name, category, cost, hours, desc in rows:
            aid += 1
            w(f"INSERT INTO attraction (attraction_id, destination_id, name, category, "
              f"description, typical_cost, duration_hours) VALUES "
              f"({aid}, {i}, '{q(name)}', '{q(category)}', '{q(desc)}', {cost}, {hours});")

    # ── hotels (curated where available, else generated) ──
    w("\n-- hotels --")
    hid = 0
    for i, d in enumerate(DESTINATIONS, 1):
        rows = CURATED_HOTELS.get(d["city"]) or gen_hotels(d["city"], d["budget"])
        for name, area, stars, price in rows:
            hid += 1
            rating = round(RNG.uniform(3.8, 4.9), 1)
            w(f"INSERT INTO hotel (hotel_id, destination_id, name, area, stars, rating, "
              f"nightly_price) VALUES "
              f"({hid}, {i}, '{q(name)}', '{q(area)}', {stars}, {rating}, {price});")

    # ── events (curated where available, else generated) ──
    w("\n-- events --")
    eid = 0
    for i, d in enumerate(DESTINATIONS, 1):
        rows = CURATED_EVENTS.get(d["city"]) or gen_events(d["city"])
        for name, category, start, end, desc in rows:
            eid += 1
            w(f"INSERT INTO event (event_id, destination_id, name, category, start_date, "
              f"end_date, description) VALUES "
              f"({eid}, {i}, '{q(name)}', '{q(category)}', '{start}', '{end}', '{q(desc)}');")

    # ── flights (from every origin to every destination, both ways, all dates) ──
    w("\n-- flights --")
    fid = 0
    dest_region = {d["code"]: d["region"] for d in DESTINATIONS}

    def add_flight(o_city, o_code, o_region, d_city, d_code, d_region, date):
        nonlocal fid
        fid += 1
        same_region = o_region == d_region
        is_hop = o_code in DOMESTIC_HOP_CODES and d_code in DOMESTIC_HOP_CODES
        airline, iata = RNG.choice(DOMESTIC_AIRLINES if is_hop else AIRLINES)
        # Intra-Greece island hops (Athens/Santorini/Mykonos) are short nonstops.
        if is_hop:
            dur = RNG.choice([40, 45, 50, 55, 60, 70])
            stops = 0
        elif same_region:
            dur = RNG.choice([80, 95, 110, 130, 150, 175])
            stops = RNG.choice([0, 0, 0, 0, 1])
        else:
            dur = REGION_DUR.get(d_region, 600) + RNG.randint(-120, 180)
            stops = RNG.choice([0, 0, 1, 1, 2])
        if stops:
            dur += RNG.choice([70, 110, 160, 210]) * stops
        dep = RNG.choice([6 * 60, 8 * 60 + 15, 10 * 60 + 45, 13 * 60 + 30,
                          16 * 60, 19 * 60 + 20, 22 * 60 + 40])
        arr = (dep + dur) % (24 * 60)
        factor = REGION_PRICE_FACTOR.get(d_region, 1.0)
        if is_hop:
            price = round(RNG.uniform(55, 165), 0)   # cheap island hop
        else:
            base = (240 + dur * 0.7) * (0.5 if same_region else factor)
            if stops == 0:
                base += 110
            price = max(80, round(base + RNG.uniform(-50, 150), 0))
        num = f"{iata}{RNG.randint(100, 989)}"
        w(f"INSERT INTO flight (flight_id, airline, flight_no, origin_city, origin_code, "
          f"dest_city, dest_code, depart_date, depart_time, arrive_time, duration_min, "
          f"stops, price, cabin) VALUES "
          f"({fid}, '{q(airline)}', '{num}', '{q(o_city)}', '{o_code}', "
          f"'{q(d_city)}', '{d_code}', '{date}', '{hhmm(dep)}', '{hhmm(arr)}', "
          f"{dur}, {stops}, {price}, 'Economy');")

    for d in DESTINATIONS:
        d_code, d_region, d_city = d["code"], d["region"], d["city"]
        for o_city, o_code, o_region in ORIGINS:
            if o_code == d_code:
                continue
            for date in DEPART_DATES:
                add_flight(o_city, o_code, o_region, d_city, d_code, d_region, date)   # outbound
                add_flight(d_city, d_code, d_region, o_city, o_code, o_region, date)   # return

    for o_city, o_code, o_region, d_city, d_code, d_region in EXTRA_ROUTES:
        for date in DEPART_DATES:
            add_flight(o_city, o_code, o_region, d_city, d_code, d_region, date)
            add_flight(d_city, d_code, d_region, o_city, o_code, o_region, date)

    w("")  # bookings/booking_lines are created by the app; seed none.

    seed = "\n".join(out) + "\n"
    dst = Path(__file__).resolve().parent / "seed.sql"
    dst.write_text(seed)
    print(f"wrote {dst} — {len(DESTINATIONS)} destinations, {aid} attractions, "
          f"{hid} hotels, {eid} events, {fid} flights")


if __name__ == "__main__":
    main()
