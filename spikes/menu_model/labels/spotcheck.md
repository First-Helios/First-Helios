# Step B spot-check (20% sample)

Mark each row `ok` or write the correct label. Page labels: **menu** = the page's main content lists the venue's items (priced or not); **not_menu** includes menu *hubs* with only category links; **js_only** / **empty** = no server-rendered content (excluded from classifier metrics).

Seed `20260924`. 219 labeled pages.

## 1. Page labels

| # | page | URL | my label | format | note | ok? |
|---|---|---|---|---|---|---|
| 1 | `0872d28d84b5` | https://www.truetxbbq.com | **empty** | none | 200 with no text | |
| 2 | `d1f37cadd5e3` | http://www.sevensandwich.com/ | **empty** | none | 200 with no text | |
| 3 | `4849a1750755` | https://www.toasttab.com/fire-bowl-cafe-brodie-5601-brodie-lane-suite-550/rewardsSignup | **js_only** | toast | Toast rewards-signup URL (client-rendered; not a menu) accepted by S4 as the platform menu | |
| 4 | `786bad8e4f8a` | https://www.grubhub.com/food/krispy_krunchy_chicken | **js_only** | grubhub | Grubhub page | |
| 5 | `78909c3eedb8` | http://www.chooatx.com/ | **js_only** | other | client-rendered homepage | |
| 6 | `bb41fcc1bad5` | https://tacopalenque.com/menu | **js_only** | other | /menu client-rendered | |
| 7 | `a2996d1add85` | https://tacopalenque.com/menu/ | **js_only** | other | /menu client-rendered | |
| 8 | `d0fec1f624fd` | https://the-smokin-shack.square.site/ | **js_only** | square | Square Online site, client-rendered | |
| 9 | `12fb88721351` | https://www.starbucks.com/store-locator/store/1008672/ | **js_only** | chain | store locator | |
| 10 | `684e203a8ab6` | https://firopizza.com/menu/ | **menu** | html_cards | unpriced menu | |
| 11 | `4598f318ba72` | https://www.juiceland.com/full-menu/ | **menu** | html_cards | <h3> names (also <h3> sub-sections), 1-3 unlabeled size prices as separate divs, ingredient list; unpriced wellness shots; badge/"What's this?" noise | |
| 12 | `5c3f3d78246a` | https://eastside.com/menu/ | **menu** | html_inline | church cafe drink list: "Latte $3/$4" (two unnamed sizes), ALL-CAPS div sections, flavor lines, "$.50" extras; same name in two sections (Mocha) | |
| 13 | `cbcdb04ffbe0` | https://kapatad.com/drink-menu | **menu** | html_list | SpotHopper-style name/price div pairs; tab labels are noise, generic "List" headings are the sections | |
| 14 | `6a788f7d3b50` | https://www.hongkongharvard.com/new-page-1 | **menu** | html_inline | one <p> per item "Name 中文 – desc – $9.95"; "$5.95/11.95" size pairs; combo plates split over two <p>; market-price and unpriced drinks. NOTE: Overture website points to a Cambridge MA restaurant, not the Austin venue | |
| 15 | `a0f382a174e1` | https://hatcreekburgers.com/full-menu#feed-a-crowd | **menu** | html_cards | same page as 72940930f472 (fragment URL) | |
| 16 | `5724eae2a973` | https://firebowlcafe.com/menu/ | **menu** | html_cards | unpriced menu (build-your-own) | |
| 17 | `575abefd2796` | https://www.pretzelmaker.com/menu/ | **menu** | html_cards | unpriced chain menu; PDF links | |
| 18 | `dc96fa2f50f3` | https://www.joessliceofsicily.com/menu | **menu** | html_list | Wix: name/desc/price then an image-alt block repeating the name (noise) | |
| 19 | `d3af46c8798e` | https://www.mimiscafe.com/breakfast/ | **menu** | html_cards | unpriced breakfast menu | |
| 20 | `738f4b8c106a` | https://www.lilmamaskitchentx.com/about | **not_menu** | about | about | |
| 21 | `1e95075cc2c8` | http://www.classycakesbylori.com/ | **not_menu** | home | homepage | |
| 22 | `841619a28218` | https://www.xn--laseoradelzacahuil-q0b.com/about-9 | **not_menu** | about | about | |
| 23 | `5f62f1e2e5ab` | http://itaasstreetkitchen.com/ | **not_menu** | home | homepage with specialties teaser | |
| 24 | `4817157debb7` | https://www.mimiscafe.com/2019/03/13/mimis-brings-the-soul-of-france-to-yourtable-with-new-spring-menu/ | **not_menu** | other | 2019 press release accepted by S4 as a menu | |
| 25 | `cecc55c031c5` | https://sandysaustin.com/history/ | **not_menu** | about | history | |
| 26 | `0a9e5730d5e9` | https://jackallenskitchen.com/ | **not_menu** | home | homepage with happy-hour teaser prices | |
| 27 | `16443b60d53f` | http://www.hatcreekburgers.com | **not_menu** | home | homepage | |
| 28 | `90f43f8dbc50` | https://malachiliatx.com/reservations?source=pop_up&spot_id=409246&destination=reservations&promotion=reservations | **not_menu** | other | reservations | |
| 29 | `5b31daf72142` | http://www.kapatad.com/ | **not_menu** | home | homepage | |
| 30 | `bc120a2868b9` | https://www.toasttab.com/jakst/marketing-signup | **not_menu** | other | Toast marketing signup accepted by S4 as a platform menu | |
| 31 | `717bb6190eec` | https://locations.villaitaliankitchen.com/location-list/us | **not_menu** | location | locations directory | |
| 32 | `de694984a273` | https://www.pluckers.com/employment/employment-landing-staff | **not_menu** | other | employment page | |
| 33 | `b481b890244a` | https://www.peets.com/pages/accessibility-policy | **not_menu** | other | accessibility policy | |
| 34 | `50fe88910db3` | https://www.tacobell.com/menu | **not_menu** | hub | chain /menu category hub, no items | |
| 35 | `13af46798dc6` | http://www.tacobell.com/ | **not_menu** | home | homepage | |
| 36 | `3e61a467ecb8` | https://elmanaauthenticmexicanfood.com/ | **not_menu** | home | homepage with featured tacos | |
| 37 | `6a3d65a05b96` | https://locations.via313.com | **not_menu** | location | locations directory | |
| 38 | `35a58f20715b` | https://www.northitalia.com/email-signup/ | **not_menu** | other | email signup | |
| 39 | `76d2dddecb4b` | https://Smokeymosbbq.com/store-locations | **not_menu** | location | locations | |
| 40 | `92cda0c18a0d` | https://www.emarestaurants.com/austin | **not_menu** | home | location homepage | |
| 41 | `75c3ee37940d` | https://www.shugabees.com/contact-us/ | **not_menu** | other | contact | |
| 42 | `cff17f75beaf` | http://poolburger.com/ | **not_menu** | home | homepage; menu is a linked PDF (not fetched) | |
| 43 | `68e6becff088` | https://www.gusfriedchicken.com/post/you-havent-tried-true-tennessee-comfort-food-until-youve-been-here | **not_menu** | other | blog post about dishes accepted by S4 as a menu | |
| 44 | `686f78f60aa3` | http://www.hongkongharvard.com | **not_menu** | home | homepage | |
| 45 | `640ccbcec82c` | https://littlecountrydiner.com/about-Our-Story.php | **not_menu** | about | about (serves homepage) | |
| 46 | `c78123008f71` | https://locations.villaitaliankitchen.com/en-us/tx/cedar-park/11200-lakeline-mall-dr/ | **not_menu** | location | chain location page | |

## 2. Block labels and gold items (25 block-labeled menus)

### `40ceefcbb6e6` https://consueloskitchen.com/menu-la-cocina-de-consuelo/

"Name 8.00" divs (no $), description <p>, many "Add ... 2.00" modifiers; burritos repeat the name in a block above; weekday lunch specials priced only in the section heading (two time-of-day prices)

Blocks (unlisted blocks inside the region are noise):

| block | my label | text | ok? |
|---|---|---|---|
| b0019 | description | Machacado (dry spiced beef), egg, pico de gallo. | |
| b0035 | description | Slow-simmered beef. Served with rice instead of breakfast potatoes. | |
| b0037 | description | Machacado (dry spiced beef), egg, and pico de gallo. | |
| b0044 | item | Huevos Rancheros Plate* 11.50 | |
| b0050 | modifier | Add Queso Fundido to your Plate 2.00 | |
| b0052 | section | Appetizers | |
| b0057 | item | Chori-Queso 10.00 | |
| b0059 | section | Quesadillas & Nachos | |
| b0076 | item | Beef or Chicken Enchiladas Plate 15.99 | |
| b0077 | description | Two enchiladas of the same kind. Choose from: beef enchilada with chili con carne sauce or chicken enchilada w | |
| b0082 | item | Fajita Taco Plate* 16.99 | |
| b0086 | description | Two enchiladas of the same kind and one crispy beef taco. Served with a dollop of guacamole. | |
| b0088 | description | Two crispy corn tostadas of the same kind. Choice of: beef picadillo, shredded chicken, or avocado. Topped wit | |
| b0090 | item | Chicken Flautas Plate 13.99 | |
| b0097 | description | Beef steak grilled with serrano peppers, tomatoes, and onions and your choice of flour or corn tortillas. | |
| b0099 | description | Three beef fajita tacos sautéed with onions and served on corn tortillas. | |
| b0101 | description | Three beef tacos on corn tortillas. Beef is marinated with Achiote chile then grilled to perfection with pinea | |
| b0107 | item | Chicken Tortilla Soup and Taco Combo 13.99 | |
| b0117 | section | Daily Lunch Specials 11AM to 2PM - 11.99 | |
| b0122 | item | Monday - Chicken Flautas | |
| b0127 | item | Thursday - Chicken Tortilla Soup & Taco Combo | |
| b0133 | item | Apple Juice or Orange Juice 3.00 | |
| b0134 | item | Bottle of water 3.00 | |

Gold items:

| block | section | name | prices (variant:amount) | block text | ok? |
|---|---|---|---|---|---|
| b0018 | Breakfast Burritos | Machacado Burrito | -:8.00 | Machacado Burrito 8.00 | |
| b0021 | Breakfast Burritos | Barbacoa Burrito | -:8.00 | Barbacoa Burrito 8.00 | |
| b0044 | Breakfast Plates | Huevos Rancheros Plate* | -:11.50 | Huevos Rancheros Plate* 11.50 | |
| b0054 | Appetizers | Queso for 2 | -:7.00 | Queso for 2 7.00 | |
| b0064 | Quesadillas & Nachos | Nachos Compuestos | -:10.00 | Nachos Compuestos 10.00 | |
| b0085 | Plates | Combo Plate | -:17.99 | Combo Plate 17.99 | |
| b0090 | Plates | Chicken Flautas Plate | -:13.99 | Chicken Flautas Plate 13.99 | |
| b0096 | Plates | Bistec a la Mexicana* | -:16.99 | Bistec a la Mexicana* 16.99 | |
| b0111 | Soups y más | Taco Salad | -:12.50 | Taco Salad 12.50 | |
| b0138 | Beverages | Jarritos Mexican bottled sodas | -:4.00 | Jarritos Mexican bottled sodas 4.00 | |

### `0580f923bc5e` https://www.tex-mex-joes-n-lamar.com/blank

Wix: "Name Description 9.99" in one <p>; SM/LG variant price lines; SUB SHRIMP variant; shared-price agua fresca flavors

Blocks (unlisted blocks inside the region are noise):

| block | my label | text | ok? |
|---|---|---|---|
| b0029 | item | Veggie Tacos Black Beans, spinach, mushrooms and avocado slices, topped with lettuce, tomatoes and jack cheese | |
| b0031 | item | Spinach Enchiladas Filled with spinach, mushrooms, tomato and onions, with tomatillo sauce and jack cheese wit | |
| b0041 | item | Bottle of Water 1.99 | |
| b0042 | item | 1/2 Liter Mexican Coke 3.50 | |
| b0051 | price | (*SM 6.25 LG 9.75) | |
| b0056 | item | Beans and Cheese Nachos With jalapenos and onions 8.99 | |
| b0057 | item | Fajita Nachos Tortilla chips topped with beans, cheese, and choice of beef or chicken fajita, with lettuce, to | |
| b0059 | price | SUB SHRIMP 12.99 | |

Gold items:

| block | section | name | prices (variant:amount) | block text | ok? |
|---|---|---|---|---|---|
| b0016 | Desserts | Tres Leches Cake | -:6.99 | Tres Leches Cake ~ Chocolate cake soaked in three milks 6.99 | |
| b0029 | VEGETARIAN | Veggie Tacos | -:9.99 | Veggie Tacos Black Beans, spinach, mushrooms and avocado slices, topped with let | |
| b0035 | VEGETARIAN | Veggie Stuffed Avocado | -:11.99 | Veggie Stuffed Avocado Filled with spinach, tomato, onion, black beans 11.99 | |
| b0040 | Drinks | Can Soda | -:1.99 | Can Soda 1.99 | |
| b0050 | Starters | Queso | SM:6.25, LG:9.75 | Queso With chips and salsa | |
| b0055 | Starters | Happy Nachos | -:11.99 | Happy Nachos Tortilla Chips topped with cheeese picadillo, lettuce, tomatoes, an | |

### `7e3a83b84a97` https://www.juiceland.com/best-sellers/

best-sellers subset of the chain menu: image alt text, <h3> name, size prices, ingredients

Blocks (unlisted blocks inside the region are noise):

| block | my label | text | ok? |
|---|---|---|---|
| b0050 | price | $8.95 | |
| b0057 | item | Originator | |
| b0061 | description | apple, almondmilk, banana, blueberry, cherry, peanut butter, spirulina, pick your protein: pea, hemp, whey (+$ | |
| b0079 | description | award-winning hummus, quinoa tabouli (gluten-free), Kalamata Olives, Lemon, Parsley, Paprika | |
| b0092 | item | Tigerlilly | |
| b0095 | price | $13.95 | |
| b0103 | price | $7.95 | |

Gold items:

| block | section | name | prices (variant:amount) | block text | ok? |
|---|---|---|---|---|---|
| b0092 |  | Tigerlilly | -:8.95, -:10.95, -:13.95 | Tigerlilly | |
| b0102 |  | Morning Sunshine | -:7.95, -:8.95, -:10.95 | Morning Sunshine | |

### `1b6233a80694` https://www.pluckers.com/menu

item names are <h2> like section names; price 1-3 blocks after the name behind an icon-legend block; wing sauces labeled modifier (unpriced choices)

Blocks (unlisted blocks inside the region are noise):

| block | my label | text | ok? |
|---|---|---|---|
| b0020 | section | sauces | |
| b0032 | modifier | Maple Chipotle | |
| b0037 | modifier | Manganero | |
| b0053 | section | Pluckers Originals | |
| b0068 | modifier | Hallelujah | |
| b0073 | modifier | Spicy Garlic Parmesan | |
| b0088 | modifier | Goldrush | |
| b0096 | modifier | Spicy Mandarin | |
| b0105 | section | Traditional Flavors | |
| b0111 | modifier | Buffalo Medium | |
| b0121 | modifier | Spicy BBQ | |
| b0131 | modifier | Teriyaki | |
| b0149 | item | Fried Pickles | |
| b0154 | description | At Pluckers, we fry everything - even macaroni and cheese. | |
| b0167 | price | $11.00 | |
| b0174 | description | Your favorite dip for your chip | |
| b0177 | item | Pluckers Nachos | |
| b0191 | description | 1 lbs of wings tossed in your sauce of choice. | |
| b0202 | item | 5 Wing Combo | |
| b0203 | description | 1 lbs of Wings tossed in your sauce of choice. Comes with a side! | |
| b0206 | item | 10 Wing Combo | |
| b0220 | description | 1/2 lb of meatless "chicken" tenders tossed in your favorite wing sauce and served with a side. | |
| b0230 | price | $17.00 | |
| b0239 | price | $16.50 | |
| b0273 | item | Chicken Cheesesteak | |
| b0274 | description | Thinly sliced chicken smothered in grilled onions and queso. | |
| b0277 | item | The Larry Bird | |
| b0282 | description | Texas toast smothered in butter, melted American cheese, and maternal love. Thanks Mom. | |
| b0289 | item | Buffalo Chicken Sandwich | |
| b0293 | section | salads | |
| b0303 | description | A garden salad with chopped chicken tenders tossed in your favorite wings sauce. Bacon and cheese upon request | |
| b0309 | price | $15.00 | |
| b0324 | item | Tater Tots | |
| b0327 | item | Homemade Potato Chips | |
| b0338 | price | $8.50 | |
| b0340 | description | A Texas State Fair favorite made with real OREO Cookies served with a scoop of Blue Bell vanilla ice cream | |

Gold items:

| block | section | name | prices (variant:amount) | block text | ok? |
|---|---|---|---|---|---|
| b0149 | Pregame | Fried Pickles | -:5.50 | Fried Pickles | |
| b0173 | Pregame | Chips & Queso | -:8.50 | Chips & Queso | |
| b0223 | JUmbo tenders | Jumbo Tenders Basket | -:16.00 | Jumbo Tenders Basket | |
| b0240 | Burgers | The Dirty Patty Melt | -:16.00 | The Dirty Patty Melt | |
| b0248 | Burgers | Boring Burger | -:15.50 | Boring Burger | |
| b0261 | Sandwiches | Cheech and Chong | -:17.00 | Cheech and Chong | |
| b0265 | Sandwiches | Chicken Club | -:16.00 | Chicken Club | |
| b0277 | Sandwiches | The Larry Bird | -:15.50 | The Larry Bird | |
| b0281 | Sandwiches | Mom's Grilled Cheese | -:11.00 | Mom's Grilled Cheese | |
| b0310 | salads | Southwest Caesar | -:15.00 | Southwest Caesar | |

### `53172819459a` https://www.thaispoonrestaurant.com/dinner-menu/

<h3> name, "$15.00" div, description <p>; h2+h1 repeat each section; soups "Chicken (Cup) $5.00" variant lines; "$19.5" one-decimal prices

Blocks (unlisted blocks inside the region are noise):

| block | my label | text | ok? |
|---|---|---|---|
| b0013 | description | Crispy Thai rolls stuffed with vegetables and bean threads served with sweet chili sauce. | |
| b0014 | item | Summer Rolls (Shrimp or Tofu) | |
| b0024 | price | $10.00 | |
| b0031 | description | Shrimp and chicken wrapped in wanton wrapper, deep-fried, and served with sweet chili sauce. | |
| b0033 | price | $10.00 | |
| b0035 | item | Tulip Dumpling | |
| b0041 | item | Thai spoon Wings | |
| b0045 | price | $9.00 | |
| b0049 | description | Thai-style chicken meatballs, fried and served with Srirach mayo sauce. | |
| b0050 | section | Entrée: Fish | |
| b0054 | price | $24.95 | |
| b0055 | description | Fresh Fish of the day deep-fried and topped with house special sweet and spicy chili sauce. | |
| b0061 | description | Fresh Fish of the day deep-fried and topped with vegetables and sweet & sour sauce. | |
| b0074 | item | Under the Sea | |
| b0079 | description | Marinated shrimp with vegetables and glass noodles in special mild sauce, smoked and cooked in the pot. | |
| b0085 | description | Deep-fried shrimp served on steamed vegetables topped with sweet and spicy chili sauce. | |
| b0088 | item | Pad Thai | |
| b0092 | price | $15.00 | |
| b0096 | description | Pan-fried wide noodles topped with Thai style mild gravy and brocoli. | |
| b0097 | item | Lad-Na Mee Krob | |
| b0101 | price | $15.00 | |
| b0107 | price | $15.00 | |
| b0112 | item | Tom Yum Noodle Soup | |
| b0113 | price | $15.00 | |
| b0119 | price | $15.00 | |
| b0120 | description | Spicy stir-fried rice with egg, basil, chili, onion, bell pepper and scallion. | |
| b0125 | price | $15.00 | |
| b0131 | description | Fresh salmon cooked in chuchee red curry, coconut milk, kaffir lime leaves, and basil served over steamed vege | |
| b0133 | price | $18.95 | |
| b0143 | price | $7.00 | |
| b0144 | description | Side to choose from: Steamed rice, steamed noodles, or steamed vegetables. | |
| b0163 | description | Thai coconut milk soup with lemongrass flavor, chicken, mushrooms, onions, lime juice and scallions. | |
| b0165 | price | Cup $5.75 | |
| b0166 | price | Bowl $11.50 | |
| b0168 | item | Wonton | |
| b0171 | description | Chicken wontons in clear broth, with vegetables. | |
| b0176 | section | Salads | |
| b0180 | description | Cucumber, onion and carrot marinated in sweet tangy dressing | |
| b0182 | price | $9.00 | |
| b0185 | price | $9.00 | |
| b0200 | section | Entrée: Duck / Chicken | |
| b0207 | price | $19.95 | |
| b0209 | section | Main Dishes | |
| b0221 | price | $15.00 | |
| b0239 | price | $15.95 | |
| b0242 | price | $15.95 | |
| b0244 | item | Black Pepper | |
| b0248 | price | $15.95 | |
| b0254 | price | $15.95 | |
| b0256 | item | Mixed Vegetables | |
| b0257 | price | $15.95 | |
| b0269 | description | A scoop of vanilla ice cream covered with tasty pound cake and deep-fried. | |

Gold items:

| block | section | name | prices (variant:amount) | block text | ok? |
|---|---|---|---|---|---|
| b0032 | Appetizers | Satay | -:10.00 | Satay | |
| b0035 | Appetizers | Tulip Dumpling | -:9.50 | Tulip Dumpling | |
| b0038 | Appetizers | Fried Calamari | -:10.00 | Fried Calamari | |
| b0077 | Entrée: Seafood | Smokey Pot | -:18.50 | Smokey Pot | |
| b0080 | Entrée: Seafood | Thai Spoon’s Crown | -:18.50 | Thai Spoon’s Crown | |
| b0091 | Noodles and Fried Rice | Pad Se-Ew | -:15.00 | Pad Se-Ew | |
| b0094 | Noodles and Fried Rice | Pad Lad-Na | -:15.00 | Pad Lad-Na | |
| b0103 | Noodles and Fried Rice | Pad Egg Noodle | -:16.00 | Pad Egg Noodle | |
| b0106 | Noodles and Fried Rice | Pad Woon Sen | -:15.00 | Pad Woon Sen | |
| b0109 | Noodles and Fried Rice | Noodle Soup | -:15.00 | Noodle Soup | |
| b0124 | Noodles and Fried Rice | Green Curry Fried Rice | -:15.00 | Green Curry Fried Rice | |
| b0172 | Soups | Vegetables and Tofu | Cup:5.00, Bowl:10.00 | Vegetables and Tofu | |
| b0197 | Salads | Larb | -:15.50 | Larb | |
| b0206 | Entrée: Duck / Chicken | Basil Duck | -:19.95 | Basil Duck | |
| b0226 | Main Dishes | Massamun Curry | -:15.00 | Massamun Curry | |
| b0276 | Desserts | Fried Cheese Cake | -:6.00 | Fried Cheese Cake | |
