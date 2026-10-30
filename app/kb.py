"""Tiny food knowledge base: shelf life, allergens, diet flags. Rough, on purpose."""
import re

# key|category|default location|life days (fridge/pantry; or freezer window if loc=freezer)|freezer window days|allergens|flags|price $|aliases
_RAW = """
chicken breast|protein|fridge|2|270||meat,slow|4.0|chicken,chicken breasts,chicken tenders
chicken thighs|protein|fridge|2|270||meat,slow|3.5|chicken thigh,chicken legs,drumsticks,chicken drumsticks
ground beef|protein|fridge|2|120||meat,slow|5.5|hamburger meat,ground chuck,mince,beef mince
ground turkey|protein|fridge|2|120||meat,slow|5|turkey mince
steak|protein|fridge|3|180||meat,slow|9|beef steak,sirloin,ribeye,strip steak,flank steak,beef
pork chops|protein|fridge|3|150||meat,slow|4.5|pork chop,pork loin,pork
bacon|protein|fridge|7|30||meat,sodium,slow|5|bacon strips
sausage|protein|fridge|5|60||meat,sodium,slow|4|sausages,italian sausage,bratwurst,kielbasa
salmon|protein|fridge|2|90|fish|fish,slow|8|salmon fillet,salmon fillets
white fish|protein|fridge|2|90|fish|fish,slow|6|cod,tilapia,haddock,fish fillets,fish fillet,frozen fish,fish
shrimp|protein|fridge|2|180|shellfish|shellfish,quick|7|prawns,frozen shrimp
deli turkey|protein|fridge|5|60||meat,sodium|4|deli meat,lunch meat,sliced turkey,ham,sliced ham
eggs|protein|fridge|28|0|egg|animal|3.5|egg,dozen eggs
tofu|protein|fridge|7|150|soy||2.5|firm tofu,extra firm tofu
tuna|protein|pantry|730|0|fish|fish|1.5|canned tuna,tuna can,tuna cans
black beans|protein|pantry|730|0||carb|1.2|canned black beans,beans,pinto beans,kidney beans
chickpeas|protein|pantry|730|0||carb|1.2|garbanzo beans,canned chickpeas
lentils|protein|pantry|730|0||carb|2|red lentils,green lentils,brown lentils
milk|dairy|fridge|7|90|dairy|animal|3.5|whole milk,2% milk,skim milk,milk jug,carton of milk
yogurt|dairy|fridge|14|0|dairy|animal|1|greek yogurt,yoghurt,yogurts,yogurt cups
cheddar|dairy|fridge|28|180|dairy|animal|4|cheddar cheese,cheese,shredded cheese,sliced cheese,american cheese,monterey jack
mozzarella|dairy|fridge|21|180|dairy|animal|4|mozzarella cheese,fresh mozzarella
parmesan|dairy|fridge|60|180|dairy|animal|5|parmesan cheese,grated parmesan,parm,parmigiano
butter|dairy|fridge|60|270|dairy|animal|4.5|stick of butter,salted butter
heavy cream|dairy|fridge|7|90|dairy|animal|3.5|cream,whipping cream,half and half
sour cream|dairy|fridge|14|0|dairy|animal|2|
cream cheese|dairy|fridge|14|0|dairy|animal|2.5|
spinach|veg|fridge|5|180|||3|baby spinach
salad greens|veg|fridge|5|0|||3.5|lettuce,romaine,mixed greens,arugula,salad,spring mix,kale,iceberg lettuce
broccoli|veg|fridge|6|240|||2.5|broccoli florets,frozen broccoli
carrots|veg|fridge|21|240|||1.5|carrot,baby carrots
bell pepper|veg|fridge|8|240|||1.5|bell peppers,peppers,red pepper,green pepper,pepper
onion|veg|pantry|30|0|||1|onions,yellow onion,red onion,white onion
garlic|veg|pantry|60|0|||0.7|garlic cloves,garlic bulb
tomatoes|veg|fridge|6|0|||3|tomato,cherry tomatoes,grape tomatoes,roma tomatoes
cucumber|veg|fridge|7|0|||1|cucumbers
zucchini|veg|fridge|6|240|||1.5|squash,courgette,yellow squash
mushrooms|veg|fridge|6|0|||3|mushroom,button mushrooms
potatoes|veg|pantry|30|0||carb|3|potato,russet potatoes,baby potatoes,red potatoes
sweet potatoes|veg|pantry|30|0||carb|2|sweet potato,yams
celery|veg|fridge|14|0|||2|celery stalks
cabbage|veg|fridge|14|0|||2|red cabbage
green beans|veg|fridge|6|240|||2.5|string beans,asparagus
avocado|veg|pantry|4|0|||1.5|avocados
mixed vegetables|veg|freezer|365|365|||2|frozen vegetables,frozen veg,frozen peas,peas,frozen corn,corn,stir fry vegetables,frozen mixed vegetables
lemon|fruit|fridge|21|0|||0.6|lemons,lime,limes
bananas|fruit|pantry|5|90|||1|banana
apples|fruit|fridge|21|0|||2|apple
berries|fruit|fridge|5|240|||4|strawberries,blueberries,raspberries,blackberries,frozen berries,strawberry,blueberry
oranges|fruit|fridge|14|0|||3|orange,clementines,mandarins,grapes
bread|grain|pantry|6|90|gluten|carb,refined|3|sandwich bread,loaf,bagels,toast,whole wheat bread,sourdough,buns,rolls
tortillas|grain|pantry|10|180|gluten|carb|3|flour tortillas,wraps,tortilla
pasta|grain|pantry|730|0|gluten|carb,refined|1.5|spaghetti,penne,macaroni,rotini,fettuccine,linguine
noodles|grain|pantry|730|0|gluten|carb,refined|1.5|ramen,egg noodles,ramen noodles,lo mein
rice|grain|pantry|730|0||carb|2|white rice,brown rice,jasmine rice,basmati,bag of rice
oats|grain|pantry|365|0||carb|3|oatmeal,rolled oats
breadcrumbs|grain|pantry|365|0|gluten|carb|2|panko
cereal|grain|pantry|180|0|gluten|carb,sugar|4|granola
pasta sauce|pantry|pantry|365|0|||2.5|marinara,spaghetti sauce,tomato sauce,jarred sauce,marinara sauce
canned tomatoes|pantry|pantry|730|0|||1.5|diced tomatoes,crushed tomatoes,tomato can,canned diced tomatoes
tomato soup|pantry|pantry|730|0||sodium|2|canned soup,soup
chicken broth|pantry|pantry|365|0|||2.5|broth,stock,chicken stock,vegetable broth,beef broth
soy sauce|pantry|pantry|730|0|soy,gluten|sodium|3|tamari
coconut milk|pantry|pantry|730|0|||2.5|
salsa|pantry|fridge|30|0|||3|
pesto|pantry|fridge|14|0|tree nuts,dairy|animal|4|basil pesto
mayo|pantry|fridge|60|0|egg|animal|3|mayonnaise
peanut butter|pantry|pantry|180|0|peanuts||3|pb,jar of peanut butter,almond butter
honey|pantry|pantry|730|0||sugar,animal|4|maple syrup,syrup
hummus|pantry|fridge|10|0|sesame||4|tahini
almonds|pantry|pantry|180|0|tree nuts||5|walnuts,pecans,cashews,nuts,mixed nuts,pistachios
taco seasoning|pantry|pantry|730|0||sodium|1|
frozen pizza|prepared|freezer|180|180|gluten,dairy|sodium,refined,quick|5|pizza
frozen fries|prepared|freezer|240|240||carb,refined,quick|3|french fries,fries,tater tots,potato wedges
frozen dumplings|prepared|freezer|180|180|gluten,soy|sodium,carb,quick|6|dumplings,potstickers,gyoza
ice cream|prepared|freezer|120|120|dairy|sugar,animal,quick|5|gelato,popsicles,ice cream tub
orange juice|drink|fridge|10|0||sugar|3|juice,apple juice
"""

STAPLES = {"salt", "pepper", "oil", "olive oil", "vegetable oil", "water", "sugar", "flour", "spices", "garlic powder", "cooking oil"}
GENERIC_LIFE = {"fridge": 14, "freezer": 120, "pantry": 180}

FOODS = {}
ALIASES = {}
for _line in _RAW.strip().splitlines():
    k, cat, loc, life, fz, alg, flags, price, al = _line.split("|")
    FOODS[k] = dict(key=k, cat=cat, loc=loc, life=int(life), freezer=int(fz) or 0,
                    allergens=set(a for a in alg.split(",") if a), flags=set(f for f in flags.split(",") if f),
                    price=float(price))
    ALIASES[k] = k
    for a in al.split(","):
        a = a.strip()
        if a:
            ALIASES[a] = k

# consumption rate per day (chance an item is used up), by category
RATE = {"protein": 0.14, "dairy": 0.10, "veg": 0.10, "fruit": 0.12, "grain": 0.015,
        "pantry": 0.006, "prepared": 0.02, "drink": 0.12, "other": 0.01}
RATE_KEY = {"milk": 0.16, "eggs": 0.07, "bread": 0.12, "bananas": 0.15, "yogurt": 0.10}

def norm(s):
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9% ]+", " ", s)
    s = re.sub(r"\b(some|the|a|an|of|fresh|organic|packs?|packages?|bags?|cartons?|containers?|bottles?|jars?|cans?|loaf|bunch)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def canon(name):
    """Map free text to (key, known). Unknown foods keep a cleaned name."""
    raw = (name or "").lower().strip()
    n = norm(name)
    for cand in (raw, n):
        if cand in ALIASES:
            return ALIASES[cand], True
    # singular/plural
    for cand in (n.rstrip("s"), n + "s", n + "es"):
        if cand in ALIASES:
            return ALIASES[cand], True
    if re.sub(r"^frozen ", "", n) != n and re.sub(r"^frozen ", "", n) in ALIASES:
        return ALIASES[re.sub(r"^frozen ", "", n)], True
    if re.search(r"\b(sauce|dressing|seasoning|marinade|jam|jelly|chips|juice|drink|soda|tea|bar|cookies?|cake|candy|powder|oil|vinegar|creamer|spread|pickles?)\b", n):
        return n, False  # condiments/snacks shouldn't masquerade as their main word
    # whole-word containment, longest alias first
    for a in sorted(ALIASES, key=len, reverse=True):
        if len(a) >= 4 and re.search(r"\b" + re.escape(a) + r"s?\b", n):
            return ALIASES[a], True
    return (n or raw or "unknown item"), False

def info(key):
    return FOODS.get(key)

def allergens_of(key):
    f = FOODS.get(key)
    return set(f["allergens"]) if f else set()

def flags_of(key):
    f = FOODS.get(key)
    return set(f["flags"]) if f else set()
