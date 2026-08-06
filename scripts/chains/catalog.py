"""Where each chain publishes its nutrition, and what shape it's in.

One place to record, per chain: the brand domain, candidate nutrition URLs, and
once discovered, the source type an adapter should use. `discover.py` probes
these candidates in bulk so we're not hand-checking 70 websites.

`kind` matters because it decides which pipeline a chain belongs to:

* ``menu``    — a food-service chain with a published menu and macros. Needs a
                nutrition adapter; this is the pipeline that feeds the ranking.
* ``retail``  — a shop, not a kitchen. Its products are barcoded groceries, so
                nutrition comes from Open Food Facts via the meal-deal pipeline,
                not from a menu PDF. Writing a "menu adapter" for Costcutter
                would be a category error.
* ``drinks``  — coffee-led. Publishes nutrition, but the menu is drinks and
                pastries, so it rarely produces anything above the protein
                threshold. Low priority, still worth ingesting for completeness.
"""
from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class ChainSource:
    chain_id: str
    name: str
    kind: str                       # menu | retail | drinks
    domain: str = ""
    candidates: tuple[str, ...] = ()   # nutrition/allergen URL guesses
    notes: str = ""


#: Paths that UK chains commonly use for nutrition/allergen information.
COMMON_PATHS = (
    "/nutrition", "/nutritional-information", "/nutrition-allergens",
    "/allergens", "/allergen-information", "/nutrition-information",
    "/food/nutrition", "/menu/nutrition", "/our-food/nutrition",
    "/allergen-nutrition", "/nutrition.html", "/nutritionals",
)


def _c(chain_id, name, kind, domain, *extra, notes=""):
    candidates = tuple(f"https://{domain}{p}" for p in COMMON_PATHS) + tuple(extra)
    return ChainSource(chain_id, name, kind, domain, candidates, notes)


CATALOG: dict[str, ChainSource] = {c.chain_id: c for c in [
    # --- already implemented (kept so coverage reporting is honest) ---
    _c("mcdonalds", "McDonald's", "menu", "www.mcdonalds.com",
       notes="DONE — dnaapp JSON API"),
    _c("kfc", "KFC", "menu", "www.kfc.co.uk",
       "https://brand-uk.assets.kfc.co.uk/nutrition-allergens.pdf",
       notes="DONE — brand PDF"),
    _c("popeyes", "Popeyes", "menu", "popeyesuk.com",
       notes="DONE — ordering API"),
    _c("greggs", "Greggs", "menu", "www.greggs.com",
       notes="DONE — production-digital API"),
    _c("subway", "Subway", "menu", "www.subway.com",
       notes="DONE — brand PDF discovered from nutrition page"),
    _c("papa_johns", "Papa John's", "menu", "www.papajohns.co.uk",
       "https://www.papajohns.co.uk/static/assets/pdfs/nutritional-information.pdf",
       notes="DONE — brand PDF via TLS impersonation"),

    # --- burgers / chicken ---
    _c("burger_king", "Burger King", "menu", "www.burgerking.co.uk",
       "https://www.burgerking.co.uk/nutrition-explorer"),
    _c("gdk", "German Doner Kebab", "menu", "www.gdk.com",
       "https://gdk.com/gb/allergen-information?cr=1",
       notes="allergens published, macros not found on site"),
    _c("five_guys", "Five Guys", "menu", "www.fiveguys.co.uk"),
    _c("nandos", "Nando's", "menu", "www.nandos.co.uk",
       "https://www.nandos.co.uk/food/menu"),
    _c("wingstop", "Wingstop", "menu", "www.wingstop.co.uk"),
    _c("slim_chickens", "Slim Chickens", "menu", "slimchickens.co.uk"),
    _c("shake_shack", "Shake Shack", "menu", "www.shakeshack.co.uk"),
    _c("wimpy", "Wimpy", "menu", "www.wimpyburgers.co.uk"),
    _c("chicken_cottage", "Chicken Cottage", "menu", "chickencottage.com"),
    _c("dixy_chicken", "Dixy Chicken", "menu", "dixychicken.co.uk"),
    _c("morleys", "Morley's", "menu", "morleyschicken.com"),
    _c("pepes_piri_piri", "Pepe's Piri Piri", "menu", "pepespiripiri.com"),

    # --- pizza ---
    _c("dominos", "Domino's", "menu", "www.dominos.co.uk",
       "https://www.dominos.co.uk/nutrition"),
    _c("pizza_hut", "Pizza Hut", "menu", "www.pizzahut.co.uk"),
    _c("pizza_express", "PizzaExpress", "menu", "www.pizzaexpress.com"),
    _c("franco_manca", "Franco Manca", "menu", "www.francomanca.co.uk"),
    _c("zizzi", "Zizzi", "menu", "www.zizzi.co.uk"),
    _c("ask_italian", "ASK Italian", "menu", "www.askitalian.co.uk"),
    _c("papa_murphys", "Papa Murphy's", "menu", "www.papamurphys.com"),

    # --- sandwiches / bakery / asian ---
    _c("pret", "Pret A Manger", "menu", "www.pret.co.uk"),
    _c("itsu", "itsu", "menu", "www.itsu.com"),
    _c("leon", "LEON", "menu", "leon.co"),
    _c("wagamama", "wagamama", "menu", "www.wagamama.com"),
    _c("yo_sushi", "YO! Sushi", "menu", "yosushi.com"),
    _c("wasabi", "Wasabi", "menu", "www.wasabi.uk.com"),
    _c("chopstix", "Chopstix", "menu", "chopstixgroup.com"),
    _c("tortilla", "Tortilla", "menu", "tortilla.co.uk"),
    _c("chipotle", "Chipotle", "menu", "www.chipotle.co.uk"),
    _c("wok_to_walk", "Wok to Walk", "menu", "woktowalk.com"),
    _c("kokoro", "Kokoro", "menu", "kokorouk.com"),
    _c("sushi_gourmet", "Sushi Gourmet", "menu", "sushigourmet.co.uk"),
    _c("yo_to_go", "YO! To Go", "menu", "yosushi.com"),
    _c("gails", "GAIL's", "menu", "gailsbread.co.uk"),
    _c("warrens", "Warrens Bakery", "menu", "warrensbakery.co.uk"),
    _c("paul", "PAUL", "menu", "www.paul-uk.com"),
    _c("cake_box", "Cake Box", "menu", "www.eggfreecake.co.uk"),
    _c("batchd", "Batch'd", "menu", "batchd.co.uk"),
    _c("cafe_0161", "Cafe 0161", "menu", "cafe0161.co.uk"),
    _c("chaiiwala", "Chaiiwala", "menu", "chaiiwala.co.uk"),

    # --- pubs / casual dining ---
    _c("wetherspoons", "Wetherspoon", "menu", "www.jdwetherspoon.com",
       "https://www.jdwetherspoon.com/menus/nutrition"),
    _c("harvester", "Harvester", "menu", "www.harvester.co.uk"),
    _c("toby_carvery", "Toby Carvery", "menu", "www.tobycarvery.co.uk"),
    _c("beefeater", "Beefeater", "menu", "www.beefeater.co.uk"),
    _c("brewers_fayre", "Brewers Fayre", "menu", "www.brewersfayre.co.uk"),
    _c("hungry_horse", "Hungry Horse", "menu", "www.hungryhorse.co.uk"),
    _c("miller_carter", "Miller & Carter", "menu", "www.millerandcarter.co.uk"),
    _c("frankie_bennys", "Frankie & Benny's", "menu", "www.frankieandbennys.com"),
    _c("tgi_fridays", "TGI Fridays", "menu", "www.tgifridays.co.uk"),
    _c("taco_bell", "Taco Bell", "menu", "www.tacobell.co.uk"),

    # --- coffee-led ---
    _c("costa", "Costa Coffee", "drinks", "www.costa.co.uk"),
    _c("starbucks", "Starbucks", "drinks", "www.starbucks.co.uk"),
    _c("caffe_nero", "Caffè Nero", "drinks", "caffenero.com"),
    _c("tim_hortons", "Tim Hortons", "drinks", "timhortons.co.uk"),
    _c("black_sheep_coffee", "Black Sheep Coffee", "drinks", "leavetheherd.com"),
    _c("coffee_1", "Coffee #1", "drinks", "www.coffee1.co.uk"),
    _c("krispy_kreme", "Krispy Kreme", "drinks", "www.krispykreme.co.uk"),
    _c("hotel_chocolat", "Hotel Chocolat", "drinks", "www.hotelchocolat.com"),

    # --- retail: nutrition comes from Open Food Facts, not a menu ---
    *[ChainSource(cid, nm, "retail", dom, (), "OFF barcode pipeline")
      for cid, nm, dom in [
          ("tesco", "Tesco", "www.tesco.com"),
          ("sainsburys", "Sainsbury's", "www.sainsburys.co.uk"),
          ("asda", "Asda", "www.asda.com"),
          ("lidl", "Lidl", "www.lidl.co.uk"),
          ("aldi", "Aldi", "www.aldi.co.uk"),
          ("marks_spencer", "M&S", "www.marksandspencer.com"),
          ("boots", "Boots", "www.boots.com"),
          ("coop", "Co-op", "www.coop.co.uk"),
          ("morrisons", "Morrisons", "www.morrisons.com"),
          ("waitrose", "Waitrose", "www.waitrose.com"),
          ("spar", "Spar", "www.spar.co.uk"),
          ("premier", "Premier", "www.premier-stores.co.uk"),
          ("nisa", "Nisa", "www.nisalocally.co.uk"),
          ("londis", "Londis", "www.londis.co.uk"),
          ("budgens", "Budgens", "www.budgens.co.uk"),
          ("one_stop", "One Stop", "www.onestop.co.uk"),
          ("iceland", "Iceland", "www.iceland.co.uk"),
          ("whsmith", "WHSmith", "www.whsmith.co.uk"),
          ("costcutter", "Costcutter", "www.costcutter.co.uk"),
          ("best_one", "Best-one", "www.bestone.co.uk"),
          ("lifestyle_express", "Lifestyle Express", "www.lifestyleexpress.co.uk"),
          ("day_today", "Day-Today", "daytodayexpress.co.uk"),
          ("scotmid", "Scotmid", "www.scotmid.coop"),
          ("farmfoods", "Farmfoods", "www.farmfoods.co.uk"),
          ("holland_barrett", "Holland & Barrett", "www.hollandandbarrett.com"),
          ("home_bargains", "Home Bargains", "www.homebargains.co.uk"),
          ("poundland", "Poundland", "www.poundland.co.uk"),
          ("bm_bargains", "B&M", "www.bmstores.co.uk"),
      ]],
]}

DONE = {"mcdonalds", "kfc", "popeyes", "greggs", "subway", "papa_johns"}


def menu_chains() -> list[ChainSource]:
    return [c for c in CATALOG.values() if c.kind in ("menu", "drinks")]


def pending() -> list[ChainSource]:
    return [c for c in menu_chains() if c.chain_id not in DONE]
