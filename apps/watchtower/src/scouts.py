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
        "search_urls": [
            "https://api.prd.cloud.century21.be/api/v2/properties?facets=elevator%2Ccondition%2CfloorNumber%2Cgarden%2ChabitableSurfaceArea%2ClistingType%2CnumberOfBedrooms%2Cparking%2Cprice%2CsubType%2CsurfaceAreaGarden%2CswimmingPool%2Cterrace%2CtotalSurfaceArea%2Ctype&filter=eyJib29sIjp7ImZpbHRlciI6eyJib29sIjp7Im11c3QiOlt7ImJvb2wiOnsic2hvdWxkIjpbeyJtYXRjaCI6eyJhZGRyZXNzLmNvdW50cnlDb2RlIjoiYmUifX0seyJtYXRjaCI6eyJhZGRyZXNzLmNvdW50cnlDb2RlIjoiZnIifX0seyJtYXRjaCI6eyJhZGRyZXNzLmNvdW50cnlDb2RlIjoiaXQifX0seyJtYXRjaCI6eyJhZGRyZXNzLmNvdW50cnlDb2RlIjoibHUifX1dfX0seyJtYXRjaCI6eyJsaXN0aW5nVHlwZSI6IkZPUl9TQUxFIn19LHsicmFuZ2UiOnsicHJpY2UuYW1vdW50Ijp7Imx0ZSI6MzAwMDAwfX19LHsiYm9vbCI6eyJzaG91bGQiOnsibWF0Y2giOnsidHlwZSI6IkhPVVNFIn19fX0seyJyYW5nZSI6eyJjcmVhdGlvbkRhdGUiOnsibHRlIjoiMjAyNi0wMS0yMFQyMjowOTo1Ny40MzBaIn19fV19fX19&pageSize=24&sort=-creationDate"
        ]
    }
}
