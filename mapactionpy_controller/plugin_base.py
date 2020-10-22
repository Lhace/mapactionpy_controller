import errno
import glob
import logging
# import math
import os
from operator import itemgetter
import re
from shutil import copyfile
from zipfile import ZipFile

from slugify import slugify

from mapactionpy_controller.crash_move_folder import CrashMoveFolder
from mapactionpy_controller.event import Event


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

    def _get_all_templates_by_regex(self, recipe):
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
            logger.debug('checking file "{}", with extension "{}", against pattern "{}" and "{}"'.format(
                f, extension, recipe.template, self.get_projectfile_extension()
            ))
            if re.search(recipe.template, f):
                logger.debug('file {} matched regex'.format(f))
                f_path = os.path.join(self.cmf.map_templates, f)
                logger.debug('file {} joined with self.cmf.map_templates "{}"'.format(f, f_path))
                return (os.path.isfile(f_path)) and (extension == self.get_projectfile_extension())
            else:
                return False

        # TODO: This results in calling `os.path.join` twice for certain files
        logger.debug('searching for map templates in; {}'.format(self.cmf.map_templates))
        all_filenames = os.listdir(self.cmf.map_templates)
        logger.debug('all available template files:\n\t{}'.format('\n\t'.join(all_filenames)))
        relevant_filenames = [os.path.join(self.cmf.map_templates, fi) for fi in all_filenames if _is_relevant_file(fi)]
        logger.debug('possible template files:\n\t{}'.format('\n\t'.join(relevant_filenames)))
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
        # Target is more landscape than the most landscape template
        most_landscape = max(template_aspect_ratios, key=itemgetter(1))
        if most_landscape[1] < target_ar:
            return most_landscape[0]

        # Target is more portrait than the most portrait template
        most_portrait = min(template_aspect_ratios, key=itemgetter(1))
        if most_portrait[1] > target_ar:
            return most_portrait[0]

        # The option with the smallest aspect ratio that is larger than target_ar
        larger_ar = min(
            [(templ_path, templ_ar) for templ_path, templ_ar in template_aspect_ratios if templ_ar > target_ar],
            key=itemgetter(1))
        # The option with the largest aspect ratio that is smaller than target_ar
        smaller_ar = max(
            [(templ_path, templ_ar) for templ_path, templ_ar in template_aspect_ratios if templ_ar <= target_ar],
            key=itemgetter(1))

        # Linear combination:
        if (2*target_ar) >= (larger_ar[1] + smaller_ar[1]):
            return larger_ar[0]

        # asmith: personally I think that this is the better option, but will go with the linear combination for now
        # logarithmic combination
        # if (2*math.log(target_ar)) > (math.log(larger_ar[1]) + math.log(smaller_ar[1])):
        #     return larger_ar[0]

        return smaller_ar[0]

    def get_aspect_ratios_of_templates(self, possible_templates):
        """
        Plugins are required to implement this method.

        The implementation should calculate the aspect ratio of the principal map frame within the list of
        templates. The definition of "principal" is left to the plugin, though is typically the largest map
        frame.

        @param possible_templates: A list of paths to possible templates
        @returns: A list of tuples. For each tuple the first element is the path to the template. The second
                  element is the aspect ratio of the largest* map frame within that template.
                  See `_get_largest_map_frame` for the description of hour largest is determined.
        @raises NotImplementedError: In the base class.
        """
        raise NotImplementedError(
            'BaseRunnerPlugin is an abstract class and the `_get_aspect_ratios_of_templates`'
            ' method cannot be called directly')

    def get_templates(self, **kwargs):
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
        possible_aspect_ratios = self.get_aspect_ratios_of_templates(possible_templates)

        # use logic to workout which template has best aspect ratio
        # obviously not this logic though:
        recipe.template_path = self._get_template_by_aspect_ratio(possible_aspect_ratios, 1.0)

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
        output_map_name = '{}-v{}-{}{}'.format(
            recipe.mapnumber, str(recipe.version_num).zfill(2), output_map_base, self.get_projectfile_extension())
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
        export_params = {}
        export_params = self._create_export_dir(export_params, recipe)
        export_params = self._do_export(export_params, recipe)
        self.zip_exported_files(export_params)

    def _create_export_dir(self, export_params, recipe):
        # Accumulate parameters for export XML
        version_str = "v" + str(recipe.version_num).zfill(2)
        export_directory = os.path.abspath(
            os.path.join(self.cmf.export_dir, recipe.mapnumber, version_str))
        export_params["exportDirectory"] = export_directory

        try:
            os.makedirs(export_directory)
        except OSError as exc:  # Python >2.5
            # Note 'errno.EEXIST' is not a typo. There should be two 'E's.
            # https://docs.python.org/2/library/errno.html#errno.EEXIST
            if exc.errno == errno.EEXIST and os.path.isdir(export_directory):
                pass
            else:
                raise

        return export_params

    def _do_export(self, export_params, recipe):
        raise NotImplementedError(
            'BaseRunnerPlugin is an abstract class and the `export_maps`'
            ' method cannot be called directly')

    def zip_exported_files(self, export_params):
        # Get key params as local variables
        core_file_name = export_params['coreFileName']
        export_dir = export_params['exportDirectory']
        mdr_xml_file_path = export_params['exportXmlFileLocation']
        jpg_path = export_params['jpgFileLocation']
        png_thumbnail_path = export_params['pngThumbNailFileLocation']
        # And now Zip
        zipFileName = core_file_name+".zip"
        zipFileLocation = os.path.join(export_dir, zipFileName)

        with ZipFile(zipFileLocation, 'w') as zipObj:
            zipObj.write(mdr_xml_file_path, os.path.basename(mdr_xml_file_path))
            zipObj.write(jpg_path, os.path.basename(jpg_path))
            zipObj.write(png_thumbnail_path, os.path.basename(png_thumbnail_path))

            # TODO: asmith 2020/03/03
            # Given we are explictly setting the pdfFileName for each page within the DDPs
            # it is possible return a list of all of the filenames for all of the PDFs. Please
            # can we use this list to include in the zip file. There are edge cases where just
            # adding all of the pdfs in a particular directory might not behave correctly (eg if
            # the previous run had crashed midway for some reason)
            for pdf in os.listdir(export_dir):
                if pdf.endswith(".pdf"):
                    zipObj.write(os.path.join(export_dir, pdf),
                                 os.path.basename(os.path.join(export_dir, pdf)))
        print("Export complete to " + export_dir)

    def build_project_files(self, **kwargs):
        raise NotImplementedError(
            'BaseRunnerPlugin is an abstract class and the `build_project_files`'
            ' method cannot be called directly')
