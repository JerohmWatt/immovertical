# List of sources to scan for new listings

SCOUTS = {
    "immoweb": {
        "name": "immoweb",
        "method": "regex",
        "search_urls": [
            "https://www.immoweb.be/fr/recherche/maison/a-vendre/hainaut/province?countries=BE&isALifeAnnuitySale=false&isAnInvestmentProperty=false&isAPublicSale=false&isNewlyBuilt=false&maxPrice=1000000&page=1&orderBy=newest"
        ],
        # Example: https://www.immoweb.be/fr/annonce/maison/a-vendre/uccle/1180/11122233
        # The ID is the last numeric part of the URL.
        # Requirement: at least 7 digits for the ID to avoid postcodes (4 digits)
        "link_pattern": r"https://www\.immoweb\.be/[a-z]{2}/annonce/.*?/\d{7,}",
        "id_pattern": r"/(\d+)"
    },
    "century21": {
        "name": "century21",
        "method": "json",
        "search_urls": [] # Dynamically generated in main.py
    }
}
