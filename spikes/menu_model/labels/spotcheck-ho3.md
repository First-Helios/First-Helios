# Held-out-3 spot-check (20% of each page's blocks and gold items)

Nine new venues (candidates batch 2). Mark each row `ok` or write the correction. Unlisted blocks inside a page's region are noise; the full record is `labels/review.txt` (per-page specs in `labels/ho3/`). Seed `20260926`.

### `0507748949ae` https://pterrys.com/menu/

h2 section, h4 item, price p (two unlabeled size prices "$2.85 | $3.65" for drinks); Add-ons list is modifiers; div card titles and a "Served until 11am" h4 are noise; unpriced per-item detail sections after the menu excluded

Blocks (unlisted blocks inside the region are noise):

| block | my label | text | ok? |
|---|---|---|---|
| b0025 | item | Hamburger | |
| b0026 | price | $3.10 | |
| b0028 | price | $3.65 | |
| b0031 | item | Chicken Burger | |
| b0035 | item | Veggie Burger | |
| b0039 | price | $5.00 | |
| b0048 | price | $12.00 | |
| b0057 | section | Breakfast / Served until 11am | |
| b0064 | item | Egg Burger | |
| b0067 | price | $1.85 | |
| b0082 | item | Orange Juice | |
| b0086 | description | Organic low-fat | |

Gold items:

| block | section | name | prices (variant:amount) | block text | ok? |
|---|---|---|---|---|---|
| b0027 | Burgers & Chicken Bites | Cheeseburger | -:3.65 | Cheeseburger | |
| b0033 | Burgers & Chicken Bites | Crispy Chicken Burger | -:5.10 | Crispy Chicken Burger | |
| b0041 | Sides & Desserts | French Fries | -:2.30 | French Fries | |
| b0061 | Breakfast / Served until 11am | sausage Egg Burger | -:3.50 | sausage Egg Burger | |
| b0066 | Breakfast / Served until 11am | Breakfast Potatoes | -:1.85 | Breakfast Potatoes | |

### `0c51131daf93` https://www.revelryatx.com/menus

name div, description div, price p; add-on lines (add/sub/xtra/toss in) with their own $ div are modifiers; '.' spacer lines and the happy-hour/burger intro paragraphs are noise

Blocks (unlisted blocks inside the region are noise):

| block | my label | text | ok? |
|---|---|---|---|
| b0027 | item | Chips & Queso. | |
| b0029 | price | $12 | |
| b0038 | item | Fried Pickles | |
| b0050 | item | Big Ass Pretzel | |
| b0058 | price | $8 | |
| b0059 | item | Chili Cheese Fries | |
| b0060 | description | House-made angus beef chili, jack cheese, green onions. | |
| b0071 | item | Grilled Chicken Sandwich | |
| b0073 | item | Patty Melt | |
| b0074 | description | Served with sauteed onion, cheddar, sriracha mayo. | |
| b0075 | price | $15 | |
| b0079 | modifier | Sub Gluten Free Bun | |
| b0080 | modifier | $1 | |
| b0082 | modifier | $2 | |
| b0085 | item | Crispy Chicken Sandwich | |
| b0103 | price | $15 | |
| b0104 | item | Fish Tacos | |
| b0112 | price | $11 | |
| b0115 | price | $10 | |
| b0120 | description | Roasted Pulled Pork, Pecan Smoked Ham, swiss, provolone, pickled jalapenos, on sourdough bread. | |
| b0129 | modifier | add grilled chicken | |
| b0137 | modifier | add sunny-side up egg -or- bacon | |
| b0149 | price | $16 | |
| b0151 | description | Buttermilk Fried Chicken, Texas Toast, w Side of Ranch, Comes w Fries | |
| b0155 | price | $7 | |
| b0162 | description | (Dressing: Sesame-Ginger, Bleu Cheese, Ranch, Jalapeno-Ranch, Balsamic Vinaigrette, Blood Orange Vinaigrette) | |
| b0168 | item | Brownie Skillet | |

Gold items:

| block | section | name | prices (variant:amount) | block text | ok? |
|---|---|---|---|---|---|
| b0050 | APPETIZERS | Big Ass Pretzel | -:13.00 | Big Ass Pretzel | |
| b0095 | BURGERS/ ENTREES | Buffalo Chicken Wrap W/ Kettle Chips | -:16.00 | Buffalo Chicken Wrap W/ Kettle Chips | |
| b0104 | BURGERS/ ENTREES | Fish Tacos | -:13.00 | Fish Tacos | |
| b0131 | BURGERS/ ENTREES | 1401 Salad | -:12.00 | 1401 Salad | |
| b0144 | BURGERS/ ENTREES | Pesto Chicken Sandwich | -:16.00 | Pesto Chicken Sandwich | |
| b0147 | BURGERS/ ENTREES | Caprese Chicken Sandwich | -:16.00 | Caprese Chicken Sandwich | |
| b0150 | BURGERS/ ENTREES | Chicken Tender Basket | -:16.00 | Chicken Tender Basket | |

### `1b1cc94460b3` http://www.southsideflyingpizza.com/

Square Online cards: h2 section, name p, description p, price p; daily-special card titles/availability divs are noise; Extras (sauces, dough ball, chips) are sold items

Blocks (unlisted blocks inside the region are noise):

| block | my label | text | ok? |
|---|---|---|---|
| b0035 | price | $175.00 | |
| b0036 | item | Pizza Party for 30 - 12 X-Large Pizza | |
| b0037 | price | $265.00 | |
| b0042 | section | September Special | |
| b0047 | item | Pizza Rolls Special! | |
| b0048 | description | Four Fabulous Pizza Rolls | |
| b0056 | section | Tuesday Specials | |
| b0058 | item | King of Pepperoni! | |
| b0061 | section | Wednesday Specials | |
| b0065 | description | Pepperoni or chicken jalapeno. | |
| b0070 | item | Meatsider Pizza | |
| b0073 | section | Friday Special | |
| b0076 | item | Wings Friday | |
| b0077 | description | Five for Ten delicous baked chicken wings with your favorite sauce | |
| b0083 | description | Our Caesar Plus More Salad | |
| b0089 | price | $19.50 | |
| b0096 | item | Wings Party for 10 People | |
| b0097 | description | 40 Pieces. | |
| b0100 | description | Any Slice, Side Salad and Soda | |
| b0110 | description | Pepperoni, ham, sausage, black olives, pineapple, jalapeno peppers, mozzarella, romano, and parmesan. | |
| b0117 | price | $25.50 | |
| b0130 | item | The Athena Pizza | |
| b0131 | description | Basil, Kalamata olives, red onions, tomatoes, feta, mozzarella, parmesan, and Romano, Ricotta. | |
| b0134 | description | Basil pesto, artichoke, tomato, spinach, roasted red pepper, Roma tomato, feta, mozzarella, parmesan, and Roma | |
| b0142 | section | Giant Slices | |
| b0143 | item | King of Pepperoni Pizza Slice | |
| b0150 | description | Pepperoni, ham, sausage, black olives, pineapple, jalepenos, mozzarella, romano, and parmesan. | |
| b0157 | price | $8.50 | |
| b0159 | description | Mushrooms, red onions, tomatoes, spinach, bell peppers, mozzarella, romano, and parmesan. | |
| b0173 | item | Artichoke & Basil Pesto Pizza Slice | |
| b0181 | price | $17.00 | |
| b0184 | price | $14.00 | |
| b0189 | item | Feta & Pecan House Salad | |
| b0192 | item | Caesar (with more!) Salad | |
| b0209 | item | Bag of Chips | |
| b0220 | price | $2.50 | |
| b0231 | item | Vegan Greensider | |
| b0232 | description | Vegan cheese and a world of vegetables | |
| b0233 | price | $22.00 | |

Gold items:

| block | section | name | prices (variant:amount) | block text | ok? |
|---|---|---|---|---|---|
| b0093 | Catering - Sides | Pizza Roll Party For 12 People | -:75.00 | Pizza Roll Party For 12 People | |
| b0103 | High Flying Pizza | King of Pepperoni Pizza | -:23.50 | King of Pepperoni Pizza | |
| b0118 | High Flying Pizza | The Greensider Pizza | -:23.50 | The Greensider Pizza | |
| b0124 | High Flying Pizza | The Saxon Pizza | -:23.50 | The Saxon Pizza | |
| b0127 | High Flying Pizza | Margherita Pizza | -:23.50 | Margherita Pizza | |
| b0133 | High Flying Pizza | Artichoke & Basil Pesto Pizza | -:25.50 | Artichoke & Basil Pesto Pizza | |
| b0139 | High Flying Pizza | Garlic Chicken Special | -:23.50 | Garlic Chicken Special | |
| b0143 | Giant Slices | King of Pepperoni Pizza Slice | -:7.99 | King of Pepperoni Pizza Slice | |
| b0149 | Giant Slices | The Eastsider Pizza Slice | -:7.99 | The Eastsider Pizza Slice | |
| b0152 | Giant Slices | The Meatsider Pizza Slice | -:7.99 | The Meatsider Pizza Slice | |
| b0155 | Giant Slices | The Lakesider Pizza Slice | -:8.50 | The Lakesider Pizza Slice | |
| b0170 | Giant Slices | The Athena Pizza Slice | -:7.99 | The Athena Pizza Slice | |
| b0196 | Extras | Ranch Dressing | -:1.00 | Ranch Dressing | |

### `3cd639cd8f00` https://rollinsmokeatxbbq.com/food-menu

h2 section, h3 item, price div (inline size labels before the price, "/Pork", "/PP" suffixes), description div; some descriptions print more prices (wings with fries, quesataco fillings); catering per-person packages included, unpriced protein list excluded

Blocks (unlisted blocks inside the region are noise):

| block | my label | text | ok? |
|---|---|---|---|
| b0041 | item | Brisket Prime | |
| b0044 | price | Half $12.00 / Plate with two small sides $18.00 • Half chicken brined and smoked to perfection with a simple C | |
| b0046 | price | 1/2 lb $16.00 / Pound $32.00 • Large meaty spareribs by Prairie Fresh are smoked, then finished with our peppe | |
| b0056 | price | $16.00 | |
| b0061 | item | Chopped Beef Sandwich | |
| b0063 | description | Chopped and sauced prime brisket. | |
| b0071 | item | Player’s Pie | |
| b0078 | item | Pulled Pork Taco | |
| b0079 | price | $8.00 | |
| b0090 | price | $17.00 | |
| b0094 | description | Pickle brined, smoked, and flash fried in beef tallow 6 for $15 or $19 with fries. Choice of Dry Rub, Bbq, Hot | |
| b0101 | modifier | With Pork +$7.00 / With Brisket +$10.00 • Creamy four-cheese macaroni shells seasoned and smoked on the pit. | |
| b0102 | item | Homemade Spicy Slaw | |
| b0111 | description | Meaty Pinto Beans / Smoked Creamed Corn / Yukon Gold Potato Salad / Smoked Cheesy Hash Brown Casserole / Smoke | |
| b0113 | price | $5.00 | |
| b0114 | description | Available Saturday & Sunday • Smoked with whipped cream. | |
| b0124 | item | 2 Meats x 2 Sides | |
| b0126 | item | 3 Meats x 2 Sides | |
| b0132 | item | 4 Meats x 3 Sides | |

Gold items:

| block | section | name | prices (variant:amount) | block text | ok? |
|---|---|---|---|---|---|
| b0043 | Meats by the Pound | 48-Hour Brined Chicken | Half:12.00, Plate with two small sides:18.00 | 48-Hour Brined Chicken | |
| b0052 | Sandwiches | The Playboy | -:19.00 | The Playboy | |
| b0061 | Sandwiches | Chopped Beef Sandwich | -:15.00 | Chopped Beef Sandwich | |
| b0064 | Sandwiches | Pulled Pork Sandwich | -:14.00 | Pulled Pork Sandwich | |
| b0067 | Sandwiches | The Silky | -:16.00 | The Silky | |
| b0081 | Tacos & More | Smoked Carne Guisada Taco | -:7.00 | Smoked Carne Guisada Taco | |
| b0089 | Tacos & More | G - Thang Burrito | -:17.00 | G - Thang Burrito | |

### `60014efbcff6` https://www.frankiesnypizzapasta.com/menu

Wix-style name/desc/price divs; each section heading printed twice; pizza size label line before each price; toppings/extras are add-ons

Blocks (unlisted blocks inside the region are noise):

| block | my label | text | ok? |
|---|---|---|---|
| b0010 | section | Appetizers | |
| b0012 | item | Garlic Cheese Bread | |
| b0015 | price | $6.99 | |
| b0019 | item | Stuffed Mushrooms (2) | |
| b0020 | description | Served with a creamy sauce and light mozzarella cheese. | |
| b0021 | price | $9.99 | |
| b0022 | item | Stuffed Mushroom (3) | |
| b0027 | item | House Salad | |
| b0038 | price | $5.99 | |
| b0039 | item | Pint of Ranch Dressing | |
| b0042 | item | Calzone | |
| b0047 | price | $10.99 | |
| b0049 | item | Meatballs | |
| b0057 | price | $12.99 | |
| b0066 | price | $12.99 | |
| b0070 | item | Chicken Tuscany | |
| b0075 | price | $14.99 | |
| b0078 | price | $13.99 | |
| b0087 | price | $12.99 | |
| b0091 | item | Chicken Fettucine Alfredo | |
| b0105 | description | Pasta shells filled with ground beef, spinach and mozzarella cheese. | |
| b0107 | item | Cheese Ravioli | |
| b0113 | item | Spaghetti Works | |
| b0115 | price | $12.99 | |
| b0143 | description | Served with fresh tomatoes, sun-dried tomatoes, fresh garlic, fresh basil, olive oil and cheese. | |
| b0147 | price | $13.99 | |
| b0150 | item | Chicken Alfredo | |
| b0151 | price | 12" Small | |
| b0161 | price | $13.99 | |
| b0175 | price | 14" Medium | |
| b0179 | item | Cheese Pizza | |
| b0184 | price | 16" Large | |
| b0187 | modifier | Small Pizza Topping | |
| b0194 | price | 12" Small | |
| b0196 | price | 14" Medium | |
| b0200 | section | Seafood Entrees | |
| b0202 | price | $15.99 | |
| b0204 | price | $15.99 | |
| b0205 | item | Shrimp Marsala | |
| b0208 | price | $15.99 | |
| b0214 | price | $14.99 | |
| b0221 | item | Chicken Parmigiana | |
| b0225 | item | Philadelphia Cheese Steak | |
| b0231 | price | $5.99 | |
| b0232 | item | Kid's Cannelloni | |
| b0241 | price | $5.99 | |
| b0243 | description | With choice of plain, strawberry, chocolate or black forest. | |
| b0246 | price | $5.99 | |
| b0255 | item | Lasagna | |
| b0256 | description | With ground beef and mozzarella cheese. | |
| b0267 | item | Eggplant Parmigiana | |
| b0271 | price | $8.99 | |
| b0272 | item | Spinach Tortellini | |
| b0275 | item | Mushroom Tortellini | |
| b0278 | item | Spaghetti | |
| b0282 | description | Chicken sautéed in a white wine & hot spicy marinara sauce over Ziti pasta. | |
| b0295 | description | Sautéed chicken breast with mushrooms in a marsala wine sauce over pasta. | |

Gold items:

| block | section | name | prices (variant:amount) | block text | ok? |
|---|---|---|---|---|---|
| b0014 | Appetizers | Fried Cheese | -:6.99 | Fried Cheese | |
| b0027 | Salads | House Salad | -:2.99 | House Salad | |
| b0030 | Salads | Chicken Salad | -:10.99 | Chicken Salad | |
| b0049 | Side | Meatballs | -:5.99 | Meatballs | |
| b0051 | Side | Sausage | -:5.99 | Sausage | |
| b0070 | Chicken Entrees | Chicken Tuscany | -:13.99 | Chicken Tuscany | |
| b0205 | Seafood Entrees | Shrimp Marsala | -:15.99 | Shrimp Marsala | |
| b0207 | Seafood Entrees | Italian Sampler | -:15.99 | Italian Sampler | |
| b0213 | Seafood Entrees | Shrimp Ravioli | -:14.99 | Shrimp Ravioli | |
| b0242 | Desserts | Cheesecake | -:4.99 | Cheesecake | |
| b0245 | Desserts | Cannoli | -:5.99 | Cannoli | |
| b0258 | Lunch Specials | Manicotti | -:7.99 | Manicotti | |
| b0261 | Lunch Specials | Cannelloni | -:7.99 | Cannelloni | |
| b0269 | Lunch Specials | Pasta Trio | -:8.99 | Pasta Trio | |
| b0272 | Lunch Specials | Spinach Tortellini | -:9.99 | Spinach Tortellini | |
| b0284 | Lunch Specials | Chicken Venito | -:9.99 | Chicken Venito | |
| b0290 | Lunch Specials | Chicken Florentine | -:9.99 | Chicken Florentine | |
| b0297 | Lunch Specials | Chicken Piccata | -:9.99 | Chicken Piccata | |

### `630ef18b78a3` http://www.schoolhousepub.com/

each price printed twice: before the name (noise duplicate) and after the description (price); '+' add-on line; unpriced cocktail list; wines print a glass price plus a 'Bottle NN' line, beers a size line; happy-hour/event headings and the FAQ are outside the region

Blocks (unlisted blocks inside the region are noise):

| block | my label | text | ok? |
|---|---|---|---|
| b0034 | section | PLATES FOR SHARING | |
| b0037 | description | Fries Tossed with Slow Braised Beef, Gravy, Garlic and Cheese | |
| b0038 | price | $15 | |
| b0041 | description | Napa Cabbage, Carrots, Cilantro, Sesame Seeds, Crisp Wonton, Cashews, Pickled Thai Chile, Green Onions | |
| b0049 | description | Marinated with ginger-soy and Thai chiles with Jicama radish slaw | |
| b0064 | item | SCHOOL HOUSE PRETZEL | |
| b0065 | description | 2 Soft Pretzels with Beer Cheese & IPA Beer Mustard | |
| b0078 | description | Sriracha Veganaise, Tomato, Vegan "Cheese", Arugula | |
| b0087 | price | $15 | |
| b0097 | item | Italian Grilled Cheese | |
| b0118 | description | House- barrel aged Red Handed Bourbon, Raw Sugar, Tangerine, House Made Cherries, Bitters | |
| b0121 | item | Prom Queen | |
| b0123 | item | Mean Girls | |
| b0126 | description | Aged Rum, Ancho Reyes, Lime, Pineapple | |
| b0135 | item | Phony Negroni | |
| b0139 | item | Blue Owl Spirit Animal Sour | |
| b0156 | price | $5 | |
| b0161 | section | BOMBERS | |
| b0168 | item | School "House" Red | |
| b0169 | price | Bottle 22.00 | |
| b0176 | item | R Collection Red Blend | |
| b0180 | item | Emilio Moro Tempranillo | |
| b0181 | price | Bottle 34 | |
| b0186 | price | Bottle 22 | |
| b0190 | price | Bottle 40 | |
| b0195 | price | $8 | |

Gold items:

| block | section | name | prices (variant:amount) | block text | ok? |
|---|---|---|---|---|---|
| b0040 | PLATES FOR SHARING | ASIAN CRUNCH SALAD | -:13.00 | ASIAN CRUNCH SALAD | |
| b0060 | PLATES FOR SHARING | Whipped Goat Cheese Dip | -:13.00 | Whipped Goat Cheese Dip | |
| b0073 | BURGERS, SANDWICHES & PLATES | FISH & CHIPS | -:18.00 | FISH & CHIPS | |
| b0085 | BURGERS, SANDWICHES & PLATES | SCHOOL HOUSE PUB BURGER | -:15.00 | SCHOOL HOUSE PUB BURGER | |
| b0097 | BURGERS, SANDWICHES & PLATES | Italian Grilled Cheese | -:17.00 | Italian Grilled Cheese | |
| b0119 | Cocktails | Trapper Keeper | — | Trapper Keeper | |
| b0123 | Cocktails | Mean Girls | — | Mean Girls | |
| b0135 | Cocktails | Phony Negroni | — | Phony Negroni | |
| b0180 | RED WINES | Emilio Moro Tempranillo | Glass:11.00, Bottle:34.00 | Emilio Moro Tempranillo | |

### `8119034caa35` https://www.amicitx.com/menus

name/desc/price divs, many items then repeat their name (noise); topping and gluten-free upcharge lines are add-ons; desserts with Slice/Whole variant label lines; weekly promos are noise; wine/beer list unpriced (outside region)

Blocks (unlisted blocks inside the region are noise):

| block | my label | text | ok? |
|---|---|---|---|
| b0028 | price | $13 | |
| b0030 | price | $14 | |
| b0036 | item | Burrata with Peaches | |
| b0038 | price | $19 | |
| b0040 | price | $20 | |
| b0041 | section | Salads | |
| b0048 | price | $12 | |
| b0051 | description | Romaine lettuce, parmigiano, croutons, homemade Caesar dressing | |
| b0055 | item | 12" NY Style Cheese Pizza | |
| b0057 | modifier | 12" toppings | |
| b0069 | item | 12" NY Style Pepperoni Pizza | |
| b0074 | description | Italian sausage, pepperoni, bacon, ricotta | |
| b0084 | modifier | 12" Gluten free cauliflower pie | |
| b0085 | modifier | 12" Gluten free$9 | |
| b0101 | section | Specialty Pizza | |
| b0106 | modifier | 12" Gluten free$9 | |
| b0121 | item | Spaghetti Puttanesca | |
| b0130 | item | Spaghetti con Polpette | |
| b0131 | description | Spaghetti meatballs cooked in marinara sauce | |
| b0133 | item | Penne Arrabbiata | |
| b0139 | item | Penne Pesto | |
| b0142 | description | Creamy tomato vodka sauce | |
| b0147 | item | Fettuccine Giulio Cesare | |
| b0149 | price | $27 | |
| b0153 | item | Chicken Parmigiana | |
| b0157 | description | over pasta | |
| b0162 | item | Spaghetti alle Cozze | |
| b0167 | price | $3 | |
| b0177 | description | Whole cake, must place order 1 week prior to pick up | |
| b0180 | price | Whole Cake | |
| b0189 | price | $10 | |
| b0194 | price | $10 | |
| b0198 | item | Amici Signature Tasting | |
| b0203 | item | Sunday Sauce (Sunday's Only) Limited | |
| b0204 | description | Meatballs, Sausage, Short Ribs slowly cooked in a red sauce over pasta | |
| b0212 | price | $2 | |

Gold items:

| block | section | name | prices (variant:amount) | block text | ok? |
|---|---|---|---|---|---|
| b0023 | Appetizers | Cheesy Garlic Bread | -:10.00 | Cheesy Garlic Bread | |
| b0069 | Pizza | 12" NY Style Pepperoni Pizza | -:16.00 | 12" NY Style Pepperoni Pizza | |
| b0095 | Pizza | 12" Miele Caldo | -:23.00 | 12" Miele Caldo | |
| b0102 | Specialty Pizza | 12" Margarita | -:22.00 | 12" Margarita | |
| b0127 | Pasta | Spaghetti Carbonara | -:23.00 | Spaghetti Carbonara | |
| b0133 | Pasta | Penne Arrabbiata | -:20.00 | Penne Arrabbiata | |
| b0136 | Pasta | Penne Amatriciana | -:23.00 | Penne Amatriciana | |
| b0151 | Main Dishes | Homemade Meat Lasagna | -:25.00 | Homemade Meat Lasagna | |
| b0172 | Coffee/Desserts | Cappuccino | -:6.00 | Cappuccino | |
| b0176 | Coffee/Desserts | Jimmy's NY Style Cheesecake | Slice:10.00, Whole Cake:80.00 | Jimmy's NY Style Cheesecake | |
| b0198 | Coffee/Desserts | Amici Signature Tasting | -:75.00 | Amici Signature Tasting | |
| b0215 | Drinks | Sprite | -:2.00 | Sprite | |

### `9023e97772fa` https://www.mimadresrestaurant.com/breakfast-menu

every price printed twice: before the name (noise duplicate) and after the description (price); "-Sub ...", "Add ... for 3" add-on lines; fajitas carry a bare-number protein price line

Blocks (unlisted blocks inside the region are noise):

| block | my label | text | ok? |
|---|---|---|---|
| b0019 | section | APPETIZERS | |
| b0026 | description | Creamy fresh avocados, cilantro & pico | |
| b0030 | description | Warm, creamy and the best queso in town | |
| b0037 | item | #0 TACO | |
| b0042 | description | Sausage, egg, potato & cheese | |
| b0050 | description | Ground beef, Mexican rice & cheese | |
| b0051 | price | $4.75 | |
| b0054 | description | Black bean, eggs & cheese | |
| b0058 | description | Mushroom,chipotle,grilled onions & bell peppers | |
| b0069 | item | #8 TACO | |
| b0071 | price | $5.75 | |
| b0087 | price | $5.50 | |
| b0089 | item | #14 TACO | |
| b0091 | price | $4.75 | |
| b0097 | item | #16 TACO | |
| b0104 | section | Burritos | |
| b0108 | price | $14 | |
| b0115 | item | Veggie Rito | |
| b0126 | price | $14.50 | |
| b0139 | item | Enchiladas de la Casa | |
| b0144 | item | Chile Relleno | |
| b0149 | description | Tender braised beef stew with mexican rice served with refried beans & flour tortillas | |
| b0154 | price | $16 | |
| b0162 | item | Taco Salad | |
| b0169 | modifier | $4 | |
| b0175 | description | Texas Coffee Traders coffee brewed with brown sugar, cinnamon, Mexican chocolate & star anise | |
| b0176 | price | $5 | |
| b0195 | description | Cold brew coffee with chocolate and whipped cream | |

Gold items:

| block | section | name | prices (variant:amount) | block text | ok? |
|---|---|---|---|---|---|
| b0029 | APPETIZERS | Queso And Chips | -:11.00 | Queso And Chips | |
| b0033 | APPETIZERS | Chips and Housemade Salsa | -:3.00 | Chips and Housemade Salsa | |
| b0045 | Tacos | #2 TACO | -:5.25 | #2 TACO | |
| b0053 | Tacos | #4 TACO | -:5.25 | #4 TACO | |
| b0069 | Tacos | #8 TACO | -:5.75 | #8 TACO | |
| b0077 | Tacos | #10 TACO | -:4.00 | #10 TACO | |
| b0139 | Specialty Plates | Enchiladas de la Casa | -:16.00 | Enchiladas de la Casa | |
| b0152 | Specialty Plates | Chicken Quesadillas | -:16.00 | Chicken Quesadillas | |
| b0198 | Drinks- | Cafechata | -:5.00 | Cafechata | |

### `bf1cbf0a9e31` https://www.yukihandroll.com/menus

code + name line, short description/subtitle line, price, then dietary tag divs printed twice (noise); section intro lines are noise

Blocks (unlisted blocks inside the region are noise):

| block | my label | text | ok? |
|---|---|---|---|
| b0015 | price | $7.00 | |
| b0055 | item | C4: 5 Handrolls | |
| b0063 | description | Crab, Salmon, Tuna, Scallop, Lobster, Daily Special | |
| b0064 | price | $34.90 | |
| b0082 | description | Tuna Handroll | |
| b0109 | price | $6.00 | |
| b0114 | item | H8: Lobster | |
| b0125 | description | Toro Handroll | |
| b0144 | item | H14: Masago | |
| b0145 | description | Masago Handroll | |
| b0169 | item | H19: Japanese Uni | |
| b0192 | description | Tuna Nigiri | |
| b0197 | description | Toro Nigiri | |
| b0201 | item | N3: Chu Toro | |
| b0203 | price | $11.00 | |
| b0213 | price | $10.00 | |
| b0218 | price | $7.00 | |
| b0221 | item | N7: Salmon Belly | |
| b0241 | item | N11: Ikura | |
| b0246 | item | N12: Inari | |
| b0247 | description | Inari Nigiri | |
| b0255 | price | $5.00 | |
| b0270 | price | $8.00 | |
| b0274 | description | Amberjack (Kanpachi) Nigiri | |
| b0275 | price | $8.00 | |
| b0287 | price | $48.00 | |
| b0291 | description | 4 Chu Toro Sashimi Pieces | |
| b0292 | price | $35.00 | |
| b0302 | price | $30.00 | |
| b0315 | item | SA8: Madai | |
| b0321 | description | 4 Marinated Shrimp Sashimi Pieces | |
| b0322 | price | $21.00 | |
| b0336 | price | $5.00 | |
| b0344 | price | $7.00 | |
| b0348 | price | $12.00 | |
| b0353 | item | Tuna Roll | |
| b0366 | price | $10.00 | |
| b0374 | price | $9.00 | |
| b0379 | item | Dragon Roll | |
| b0383 | item | Rainbow Roll | |
| b0384 | price | $14.00 | |
| b0403 | item | Shaggy Dog Roll | |
| b0404 | price | $14.00 | |
| b0405 | item | Cucumber Avocado Roll | |
| b0406 | price | $8.00 | |
| b0407 | item | Tuna Avocado Roll | |
| b0414 | price | $15.50 | |

Gold items:

| block | section | name | prices (variant:amount) | block text | ok? |
|---|---|---|---|---|---|
| b0013 | Appetizers | A02: Clam Miso Soup | -:7.00 | A02: Clam Miso Soup | |
| b0114 | Handrolls | H8: Lobster | -:7.50 | H8: Lobster | |
| b0134 | Handrolls | H12: Crab | -:7.50 | H12: Crab | |
| b0191 | Nigiri | N1: Tuna | -:7.00 | N1: Tuna | |
| b0196 | Nigiri | N2: Toro | -:14.00 | N2: Toro | |
| b0206 | Nigiri | N4: Yellowtail | -:7.00 | N4: Yellowtail | |
| b0221 | Nigiri | N7: Salmon Belly | -:10.00 | N7: Salmon Belly | |
| b0231 | Nigiri | N9: Ungai | -:7.00 | N9: Ungai | |
| b0241 | Nigiri | N11: Ikura | -:7.00 | N11: Ikura | |
| b0263 | Nigiri | N15: Sweet Shrimp | -:13.00 | N15: Sweet Shrimp | |
| b0280 | Sashimi | SA1: Tuna | -:25.00 | SA1: Tuna | |
| b0285 | Sashimi | SA2: Toro | -:48.00 | SA2: Toro | |
| b0295 | Sashimi | SA4: Yellowtail | -:26.00 | SA4: Yellowtail | |
| b0393 | Sushi Roll Menu (TO GO Only) | Shrimp Tempura Roll | -:12.00 | Shrimp Tempura Roll | |
| b0409 | Sushi Roll Menu (TO GO Only) | Salmon Avocado Roll | -:10.00 | Salmon Avocado Roll | |
| b0415 | Sushi Roll Menu (TO GO Only) | Lobster Avocado Roll | -:15.50 | Lobster Avocado Roll | |
| b0421 | Sushi Roll Menu (TO GO Only) | Futo Maki | -:13.00 | Futo Maki | |
