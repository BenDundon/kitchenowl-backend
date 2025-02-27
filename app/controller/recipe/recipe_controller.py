import os
import re
import uuid

import requests
from app.util.filename_validator import allowed_file
from app.config import UPLOAD_FOLDER
from app.errors import NotFoundRequest
from app.models.recipe import RecipeItems, RecipeTags
from flask import jsonify, Blueprint
from flask_jwt_extended import jwt_required
from app.helpers import validate_args
from app.models import Recipe, Item, Tag
from recipe_scrapers import scrape_me
from recipe_scrapers._exceptions import SchemaOrgException
from werkzeug.utils import secure_filename
from .schemas import SearchByNameRequest, AddRecipe, UpdateRecipe, GetAllFilterRequest, ScrapeRecipe

recipe = Blueprint('recipe', __name__)


@recipe.route('', methods=['GET'])
@jwt_required()
def getAllRecipes():
    return jsonify([e.obj_to_full_dict() for e in Recipe.all_by_name()])


@recipe.route('/<id>', methods=['GET'])
@jwt_required()
def getRecipeById(id):
    recipe = Recipe.find_by_id(id)
    if not recipe:
        raise NotFoundRequest()
    return jsonify(recipe.obj_to_full_dict())


@recipe.route('', methods=['POST'])
@jwt_required()
@validate_args(AddRecipe)
def addRecipe(args):
    recipe = Recipe()
    recipe.name = args['name']
    recipe.description = args['description']
    if 'time' in args:
        recipe.time = args['time']
    if 'cook_time' in args:
        recipe.cook_time = args['cook_time']
    if 'prep_time' in args:
        recipe.prep_time = args['prep_time']
    if 'yields' in args:
        recipe.yields = args['yields']
    if 'source' in args:
        recipe.source = args['source']
    if 'photo' in args:
        recipe.photo = upload_file_if_needed(args['photo'])
    recipe.save()
    if 'items' in args:
        for recipeItem in args['items']:
            item = Item.find_by_name(recipeItem['name'])
            if not item:
                item = Item.create_by_name(recipeItem['name'])
            con = RecipeItems(
                description=recipeItem['description'],
                optional=recipeItem['optional']
            )
            con.item = item
            con.recipe = recipe
            con.save()
    if 'tags' in args:
        for tagName in args['tags']:
            tag = Tag.find_by_name(tagName)
            if not tag:
                tag = Tag.create_by_name(tagName)
            con = RecipeTags()
            con.tag = tag
            con.recipe = recipe
            con.save()
    return jsonify(recipe.obj_to_dict())


@recipe.route('/<id>', methods=['POST'])
@jwt_required()
@validate_args(UpdateRecipe)
def updateRecipe(args, id):  # noqa: C901
    recipe = Recipe.find_by_id(id)
    if not recipe:
        raise NotFoundRequest()
    if 'name' in args:
        recipe.name = args['name']
    if 'description' in args:
        recipe.description = args['description']
    if 'time' in args:
        recipe.time = args['time']
    if 'cook_time' in args:
        recipe.cook_time = args['cook_time']
    if 'prep_time' in args:
        recipe.prep_time = args['prep_time']
    if 'yields' in args:
        recipe.yields = args['yields']
    if 'source' in args:
        recipe.source = args['source']
    if 'photo' in args:
        recipe.photo = upload_file_if_needed(args['photo'])
    recipe.save()
    if 'items' in args:
        for con in recipe.items:
            item_names = [e['name'] for e in args['items']]
            if con.item.name not in item_names:
                con.delete()
        for recipeItem in args['items']:
            item = Item.find_by_name(recipeItem['name'])
            if not item:
                item = Item.create_by_name(recipeItem['name'])
            con = RecipeItems.find_by_ids(recipe.id, item.id)
            if con:
                if 'description' in recipeItem:
                    con.description = recipeItem['description']
                if 'optional' in recipeItem:
                    con.optional = recipeItem['optional']
            else:
                con = RecipeItems(
                    description=recipeItem['description'],
                    optional=recipeItem['optional']
                )
            con.item = item
            con.recipe = recipe
            con.save()
    if 'tags' in args:
        for con in recipe.tags:
            if con.tag.name not in args['tags']:
                con.delete()
        for recipeTag in args['tags']:
            tag = Tag.find_by_name(recipeTag)
            if not tag:
                tag = Tag.create_by_name(recipeTag)
            con = RecipeTags.find_by_ids(recipe.id, tag.id)
            if not con:
                con = RecipeTags()
                con.tag = tag
                con.recipe = recipe
                con.save()
    return jsonify(recipe.obj_to_dict())


@recipe.route('/<id>', methods=['DELETE'])
@jwt_required()
def deleteRecipeById(id):
    Recipe.delete_by_id(id)
    return jsonify({'msg': 'DONE'})


@recipe.route('/search', methods=['GET'])
@jwt_required()
@validate_args(SearchByNameRequest)
def searchRecipeByName(args):
    if 'only_ids' in args and args['only_ids']:
        return jsonify([e.id for e in Recipe.search_name(args['query'])])
    return jsonify([e.obj_to_dict() for e in Recipe.search_name(args['query'])])


@recipe.route('/filter', methods=['POST'])
@jwt_required()
@validate_args(GetAllFilterRequest)
def getAllFiltered(args):
    return jsonify([e.obj_to_full_dict() for e in Recipe.all_by_name_with_filter(args["filter"])])


@recipe.route('/scrape', methods=['GET', 'POST'])
@validate_args(ScrapeRecipe)
def scrapeRecipe(args):
    scraper = scrape_me(args['url'], wild_mode=True)
    recipe = Recipe()
    recipe.name = scraper.title()
    try:
        recipe.time = int(scraper.total_time())
    except (NotImplementedError, ValueError, SchemaOrgException):
        pass
    try:
        recipe.cook_time = int(scraper.cook_time())
    except (NotImplementedError, ValueError, SchemaOrgException):
        pass
    try:
        recipe.prep_time = int(scraper.prep_time())
    except (NotImplementedError, ValueError, SchemaOrgException):
        pass
    try:
        yields = re.search(r"\d*", scraper.yields())
        if yields:
            recipe.yields = int(yields.group())
    except (NotImplementedError, ValueError, SchemaOrgException):
        pass
    description = ''
    try:
        description = scraper.description() + "\n\n"
    except (NotImplementedError, ValueError, SchemaOrgException):
        pass
    try:
        description = description + scraper.instructions()
    except (NotImplementedError, ValueError, SchemaOrgException):
        pass
    recipe.description = description
    recipe.photo = scraper.image()
    recipe.source = args['url']
    items = {}
    for ingredient in scraper.ingredients():
        items[ingredient] = None
    return jsonify({
        'recipe': recipe.obj_to_dict(),
        'items': items,
    })


def upload_file_if_needed(url: str):
    if url is not None and '/' in url:
        from mimetypes import guess_extension
        resp = requests.get(url)
        ext = guess_extension(resp.headers['content-type'])
        if allowed_file('file' + ext):
            filename = secure_filename(str(uuid.uuid4()) + ext)
            with open(os.path.join(UPLOAD_FOLDER, filename), "wb") as o:
                o.write(resp.content)
            return filename
    elif url is not None:
        return url
    return None
