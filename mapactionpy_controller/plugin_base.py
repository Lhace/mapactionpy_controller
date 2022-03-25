import errno
import glob
import logging
import math
import os
from operator import itemgetter
import re
from shutil import copyfile
from zipfile import ZipFile

from slugify import slugify
import mapactionpy_controller.xml_exporter as xml_exporter
from mapactionpy_controller.crash_move_folder import CrashMoveFolder


logger = logging.getLogger(__name__)

# abstract class
# Done using the "old-school" method described here, without using the abs module
# https://stackoverflow.com/a/25300153


class BaseRunnerPlugin(object):
    def __init__(self, hum_event, ** kwargs):
        self.hum_event = hum_event
        self.cmf = CrashMoveFolder(self.hum_event.cmf_descriptor_path)

        if not self.cmf.verify_paths():
            raise ValueError("Cannot find paths and directories referenced by cmf {}".format(self.cmf.path))

        if self.__class__ is BaseRunnerPlugin:
            raise NotImplementedError(
                'BaseRunnerPlugin is an abstract class and cannot be instantiated directly')

    def get_projectfile_extension(self, **kwargs):
        raise NotImplementedError(
            'BaseRunnerPlugin is an abstract class and the `get_projectfile_extension`'
            ' method cannot be called directly')

    def get_lyr_render_extension(self, **kwargs):
        raise NotImplementedError(
            'BaseRunnerPlugin is an abstract class and the `get_lyr_render_extension`'
            ' method cannot be called directly')

    def _get_all_templates_by_regex(self, recipe): #Todo should we use the layoutManager from project instance 
                                                    #to get embeded templates and match the regex against their names 
        """
        Gets the fully qualified filenames of map templates, which exist in `self.cmf.map_templates` whose
        filenames match the regex `recipe.template`.

        @param recipe: A MapRecipe object.
        @returns: A list of all of the templates, stored in `cmf.map_templates` whose
                 filename matches the regex `recipe.template` and that have the extention
                 `self.get_projectfile_extension()`
        """
        def _is_relevant_file(f):

            extension = os.path.splitext(f)[1]
            logger.info('checking file "{}", with extension "{}", against pattern "{}" and "{}"'.format(
                f, extension, recipe.template, self.get_projectfile_extension()
            ))
            if re.search(recipe.template, f):
                logger.debug('file {} matched regex'.format(f))
                f_path = os.path.join(self.cmf.map_templates, f)
                logger.debug('file {} joined with self.cmf.map_templates "{}"'.format(f, f_path))
                is_relevent =  (os.path.isfile(f_path)) and (extension == self.get_projectfile_extension())
                if(is_relevent): logging.info(f"got relevent {f_path}")
                return is_relevent
            else:
                return False

        # TODO: This results in calling `os.path.join` twice for certain files
        logger.info('searching for map templates in; {}'.format(self.cmf.map_templates))
        all_filenames = os.listdir(self.cmf.map_templates)
        logger.info('all available template files:\n\t{}'.format('\n\t'.join(all_filenames)))
        relevant_filenames = [os.path.realpath(os.path.join(self.cmf.map_templates, fi))
                              for fi in all_filenames if _is_relevant_file(fi)]
        logger.info('possible template files:\n\t{}'.format('\n\t'.join(relevant_filenames)))
        return relevant_filenames

    def _get_template_by_aspect_ratio(self, template_aspect_ratios, target_ar):
        """
        Selects the template which best matches the required aspect ratio.

        @param possible_aspect_ratios: A list of tuples. For each tuple the first element is the path to the
                                       template. The second element is the relevant aspect ratio for that
                                       template. Typically this would be generated by
                                       `get_aspect_ratios_of_templates()`.
        @param target_ar: The taret aspect ratio - typically the aspect ratio of the bounding box for the country
                          being mapped.
        @returns: The path of the template with the best matching aspect ratio.
        """
        logger.info('Selecting from available templates based on the most best matching aspect ratio')

        # Target is more landscape than the most landscape template
        most_landscape = max(template_aspect_ratios, key=itemgetter(1))
        if most_landscape[1] < target_ar:
            logger.info('Target area of interest is more landscape than the most landscape template')
            return most_landscape[0]

        # Target is more portrait than the most portrait template
        most_portrait = min(template_aspect_ratios, key=itemgetter(1))
        if most_portrait[1] > target_ar:
            logger.info('Target area of interest is more portrait than the most portrait template')
            return most_portrait[0]

        # The option with the smallest aspect ratio that is larger than target_ar
        larger_ar = min(
            [(templ_path, templ_ar) for templ_path, templ_ar in template_aspect_ratios if templ_ar >= target_ar],
            key=itemgetter(1))
        # The option with the largest aspect ratio that is smaller than target_ar
        smaller_ar = max(
            [(templ_path, templ_ar) for templ_path, templ_ar in template_aspect_ratios if templ_ar <= target_ar],
            key=itemgetter(1))

        # Linear combination:
        # if (2*target_ar) > (larger_ar[1] + smaller_ar[1]):
        #     return larger_ar[0]

        # asmith: personally I think that this is the better option, but will go with the linear combination for now
        # logarithmic combination
        if (2*math.log(target_ar)) > (math.log(larger_ar[1]) + math.log(smaller_ar[1])):
            logger.info('Aspect ratio of the target area of interest lies between the aspect ratios of the'
                        ' available templates')
            return larger_ar[0]

        return smaller_ar[0]

    def get_aspect_ratios_of_templates(self, possible_templates, recipe):
        """
        Plugins are required to implement this method.

        The implementation should calculate the aspect ratio of the principal map frame within the list of
        templates. The definition of "principal" is left to the plugin, though is typically the largest map
        frame.

        @param possible_templates: A list of paths to possible templates
        @returns: A list of tuples. For each tuple the first element is the path to the template. The second
                  element is the aspect ratio of the largest* map frame within that template.
                  See `_get_largest_map_frame` for the description of how largest is determined.
        @raises NotImplementedError: In the base class.
        """
        raise NotImplementedError(
            'BaseRunnerPlugin is an abstract class and the `get_aspect_ratios_of_templates`'
            ' method cannot be called directly')

    def _get_aspect_ratio_of_bounds(self, bounds):
        minx, miny, maxx, maxy = bounds
        dx = (maxx - minx) % 360  # Accounts for the case where the bounds stradles the 180 meridian
        dy = maxy - miny

        return float(dx)/dy

    def get_templates(self, **kwargs):
        """
        Updates the recipe's `template_path` value. The result is the absolute path to the template.

        To select the appropriate template it uses two inputs.
        * The `recipe.template` value, which is a regex for the filename of the possible templates
        * The target asspect ratio. If the aspect ratio of the target data can be determined then this is
          also used to select the best matching template, amogst those which match the regex. If the
          target ratio cannot be determined fromsource gis data, then the target ratio of 1.0 will be
          used.
        """
        recipe = kwargs['state']
        # If there already is a valid `recipe.map_project_path` just skip with method
        if recipe.map_project_path:
            if os.path.exists(recipe.map_project_path):
                return recipe
            else:
                raise ValueError('Unable to locate map project file: {}'.format(recipe.map_project_path))

        # use `recipe.template` as regex to locate one or more templates
        possible_templates = self._get_all_templates_by_regex(recipe)
        
        # Select the template with the most appropriate aspect ratio
        possible_aspect_ratios = self.get_aspect_ratios_of_templates(possible_templates, recipe)
        logging.info(f"possible ARio : {possible_aspect_ratios}")
        mf = recipe.get_frame(recipe.principal_map_frame)
        # Default value
        target_aspect_ratio = 1.0
        # If the MapFrame's target extent is not None, then use that:
        if mf.extent:
            target_aspect_ratio = self._get_aspect_ratio_of_bounds(mf.extent)

        # use logic to workout which template has best aspect ratio
        # obviously not this logic though:
        recipe.template_path = self._get_template_by_aspect_ratio(possible_aspect_ratios, target_aspect_ratio)
        
        # TODO re-enable "Have the input files changed?"
        # Have the input shapefiles changed?
        return recipe

    # TODO: asmith 2020/03/03
    # 1) Please avoid hardcoding the naming convention for the mxds wherever possible. The Naming Convention
    # classes can avoid the need to hardcode the naming convention for the input mxd templates. It might be
    # possible to avoid the need to hardcode the naming convention for the output mxds using a
    # String.Template be specified within the Cookbook?
    # https://docs.python.org/2/library/string.html#formatspec
    # https://www.python.org/dev/peps/pep-3101/
    #
    # 2) This only checks the filename for the mxd - it doesn't check the values within the text element of
    # the map layout view (and hence the output metadata).
    def get_next_map_version_number(self, mapNumberDirectory, mapNumber, mapFileName):
        versionNumber = 0
        files = glob.glob(mapNumberDirectory + os.sep + mapNumber+'-v[0-9][0-9]-' + mapFileName + '.mxd')
        for file in files:
            versionNumber = int(os.path.basename(file).replace(mapNumber + '-v', '').replace(('-' + mapFileName+'.mxd'), ''))  # noqa
        versionNumber = versionNumber + 1
        return versionNumber

    # TODO Is it possible to aviod the need to hardcode the naming convention for the output mxds? Eg could a
    # String.Template be specified within the Cookbook?
    # https://docs.python.org/2/library/string.html#formatspec
    # https://www.python.org/dev/peps/pep-3101/
    def create_ouput_map_project(self, **kwargs):
        recipe = kwargs['state']
        # Create `mapNumberDirectory` for output
        output_dir = os.path.join(self.cmf.map_projects, recipe.mapnumber)

        if not(os.path.isdir(output_dir)):
            os.mkdir(output_dir)

        # Construct output MXD/QPRJ name
        logger.debug('About to create new map project file for product "{}"'.format(recipe.product))
        output_map_base = slugify(recipe.product)
        logger.debug('Set output name for new map project file to "{}"'.format(output_map_base))
        recipe.version_num = self.get_next_map_version_number(output_dir, recipe.mapnumber, output_map_base)
        recipe.core_file_name = '{}-v{}-{}'.format(
            recipe.mapnumber, str(recipe.version_num).zfill(2), output_map_base)
        output_map_name = '{}{}'.format(recipe.core_file_name, self.get_projectfile_extension())
        recipe.map_project_path = os.path.abspath(os.path.join(output_dir, output_map_name))
        logger.debug('Path for new map project file; {}'.format(recipe.map_project_path))
        logger.debug('Map Version number; {}'.format(recipe.version_num))

        # Copy `src_template` to `recipe.map_project_path`
        copyfile(recipe.template_path, recipe.map_project_path)

        return recipe

    def export_maps(self, **kwargs):
        """
        Generates all file for export.

        Accumulate some of the parameters for export XML, then calls
        _do_export(....) to do that actual work
        """
        recipe = kwargs['state']
        recipe = self._create_export_dir(recipe)
        # Do the export the map products
        recipe = self._do_export(recipe)
        # Now generate the xml file
        xml_fpath = xml_exporter.write_export_metadata_to_xml(recipe)
        recipe.zip_file_contents.append(xml_fpath)
        logger.info('Exported the map using these export_params = "{}"'.format(recipe.export_metadata))

        # Now create the zip file:
        self.zip_exported_files(recipe)
        logger.info('Created zipfile using these files = \n\t"{}"'.format("\n\t".join(recipe.zip_file_contents)))

        return recipe

    def _create_export_dir(self, recipe):
        # Accumulate parameters for export XML
        version_str = "v" + str(recipe.version_num).zfill(2)
        export_directory = os.path.abspath(
            os.path.join(self.cmf.export_dir, recipe.mapnumber, version_str))
        recipe.export_path = export_directory

        try:
            os.makedirs(export_directory)
        except OSError as exc:  # Python >2.5
            # Note 'errno.EEXIST' is not a typo. There should be two 'E's.
            # https://docs.python.org/2/library/errno.html#errno.EEXIST
            if exc.errno == errno.EEXIST and os.path.isdir(export_directory):
                pass
            else:
                raise

        return recipe

    def _do_export(self, export_params, recipe):
        """
        Note implenmenting subclasses, must return the dict `export_params`, with
        key/value pairs which satisfies the `_check_plugin_supplied_params` method.
        """
        raise NotImplementedError(
            'BaseRunnerPlugin is an abstract class and the `export_maps`'
            ' method cannot be called directly')

    def _check_paths_for_zip_contents(self, recipe):
        """
        Checks that `recipe.zip_file_contents` contains the information required to produce a zip file.
        Specificly:
        * That there is one or more entries in `recipe.zip_file_contents`.
        * That each of those entries is a path to a valid file.

        returns: None (if everything is in order)
        raises: ValueError
        """

        # First check that there is a least one entry:
        if not recipe.zip_file_contents:
            raise ValueError('No paths are specified in `recipe.zip_file_contents`')

        # Secound check that all of the entries in `recipe.zip_file_contents` point to a valid file.
        #
        # erroneous_paths = []
        # for fpath in recipe.zip_file_contents:
        #     if not os.path.isfile(fpath):
        #         erroneous_paths.append(fpath)
        erroneous_paths = [fp for fp in recipe.zip_file_contents if not os.path.isfile(fp)]

        if erroneous_paths:
            raise ValueError(
                'Cannot add the specificed files to a zip file. The following file(s) either'
                ' do not exist or are not a valid files:\n\t{}'.format('\n\t'.join(erroneous_paths)))

    def zip_exported_files(self, recipe):

        logger.debug("Started creation of zipfile")
        # First check the
        self._check_paths_for_zip_contents(recipe)

        # And now Zip
        zip_fname = recipe.core_file_name+".zip"
        zip_fpath = os.path.join(recipe.export_path, zip_fname)

        with ZipFile(zip_fpath, 'w') as zip_file:
            for fpath in recipe.zip_file_contents:
                zip_file.write(fpath, os.path.basename(fpath))

        logger.debug("Completed creation of zipfile {}".format(zip_fpath))

    def build_project_files(self, **kwargs):
        raise NotImplementedError(
            'BaseRunnerPlugin is an abstract class and the `build_project_files`'
            ' method cannot be called directly')
