__author__ = 'xuwei'
from keras.models import Model
from keras.layers import (
    Input,
    Activation,
    merge,
    Dense,
    Flatten
)
from keras.layers.convolutional import (
    Convolution2D,
    MaxPooling2D,
    AveragePooling2D
)
from keras.layers.normalization import BatchNormalization
from common_convnet.utils.utils import plot_model_cwd
import os

from keras import backend as K

if K.image_dim_ordering() == 'tf':
    INPUT_SHAPE = (224, 224, 3)
    ROW_AXIS = 1
    COL_AXIS = 2
    CHANNEL_AXIS = 3
else:
    INPUT_SHAPE = (3, 224, 224)
    CHANNEL_AXIS = 1
    ROW_AXIS = 2
    COL_AXIS = 3

dir_path = os.path.dirname(os.path.realpath(__file__))
visual_path = os.path.join(dir_path, "visual")


# Helper to build a conv -> BN -> relu block
def _conv_bn_relu(nb_filter, nb_row, nb_col, subsample=(1, 1)):
    def f(input):
        conv = Convolution2D(nb_filter=nb_filter, nb_row=nb_row, nb_col=nb_col, subsample=subsample,
                             init="he_normal", border_mode="same")(input)
        norm = BatchNormalization(mode=0, axis=CHANNEL_AXIS)(conv)
        return Activation("relu")(norm)

    return f


# Helper to build a BN -> relu -> conv block
# This is an improved scheme proposed in http://arxiv.org/pdf/1603.05027v2.pdf
def _bn_relu_conv(nb_filter, nb_row, nb_col, subsample=(1, 1)):
    def f(input):
        norm = BatchNormalization(mode=0, axis=CHANNEL_AXIS)(input)
        activation = Activation("relu")(norm)
        return Convolution2D(nb_filter=nb_filter, nb_row=nb_row, nb_col=nb_col, subsample=subsample,
                             init="he_normal", border_mode="same")(activation)

    return f


# Adds a shortcut between input and residual block and merges them with "sum"
def _shortcut(input, residual):
    # Expand channels of shortcut to match residual.
    # Stride appropriately to match residual (width, height)
    # Should be int if network architecture is correctly configured.
    stride_width = input._keras_shape[ROW_AXIS] // residual._keras_shape[ROW_AXIS]
    stride_height = input._keras_shape[COL_AXIS] // residual._keras_shape[COL_AXIS]
    equal_channels = residual._keras_shape[CHANNEL_AXIS] == input._keras_shape[CHANNEL_AXIS]

    shortcut = input
    # 1 X 1 conv if shape is different. Else identity.
    if stride_width > 1 or stride_height > 1 or not equal_channels:
        shortcut = Convolution2D(nb_filter=residual._keras_shape[CHANNEL_AXIS], nb_row=1, nb_col=1,
                                 subsample=(stride_width, stride_height),
                                 init="he_normal", border_mode="valid")(input)

    return merge([shortcut, residual], mode="sum")


# Builds a residual block with repeating bottleneck blocks.
def _residual_block(block_function, nb_filters, repetitions, is_first_layer=False):
    def f(input):
        for i in range(repetitions):
            init_subsample = (1, 1)
            if i == 0 and not is_first_layer:
                init_subsample = (2, 2)
            input = block_function(nb_filters=nb_filters, init_subsample=init_subsample)(input)
        return input

    return f


# Basic 3 X 3 convolution blocks.
# Use for resnet with layers <= 34
# Follows improved proposed scheme in http://arxiv.org/pdf/1603.05027v2.pdf
def basic_block(nb_filters, init_subsample=(1, 1)):
    def f(input):
        conv1 = _bn_relu_conv(nb_filters, 3, 3, subsample=init_subsample)(input)
        residual = _bn_relu_conv(nb_filters, 3, 3)(conv1)
        return _shortcut(input, residual)

    return f


# Bottleneck architecture for > 34 layer resnet.
# Follows improved proposed scheme in http://arxiv.org/pdf/1603.05027v2.pdf
# Returns a final conv layer of nb_filters * 4
def bottleneck(nb_filters, init_subsample=(1, 1)):
    def f(input):
        conv_1_1 = _bn_relu_conv(nb_filters, 1, 1, subsample=init_subsample)(input)
        conv_3_3 = _bn_relu_conv(nb_filters, 3, 3)(conv_1_1)
        residual = _bn_relu_conv(nb_filters * 4, 1, 1)(conv_3_3)
        return _shortcut(input, residual)

    return f


class ResNetBuilder(object):
    @staticmethod
    def build(input_shape, num_outputs, block_fn, repetitions, mode="categorical"):
        """
        Builds a custom ResNet like architecture.
        :param input_shape: The input shape in the form (nb_channels, nb_rows, nb_cols)

        :param num_outputs: The number of outputs at final softmax layer

        :param block_fn: The block function to use. This is either :func:`basic_block` or :func:`bottleneck`.
        The original paper used basic_block for layers < 50

        :param repetitions: Number of repetitions of various block units.
        At each block unit, the number of filters are doubled and the input size is halved

        :return: The keras model.
        """
        if len(input_shape) != 3:
            raise Exception("Input shape should be a tuple (nb_channels, nb_rows, nb_cols)")

        input = Input(shape=input_shape)
        conv1 = _conv_bn_relu(nb_filter=64, nb_row=7, nb_col=7, subsample=(2, 2))(input)
        pool1 = MaxPooling2D(pool_size=(3, 3), strides=(2, 2), border_mode="same")(conv1)

        block = pool1
        nb_filters = 64
        for i, r in enumerate(repetitions):
            block = _residual_block(block_fn, nb_filters=nb_filters, repetitions=r, is_first_layer=i == 0)(block)
            nb_filters *= 2

        # Classifier block
        pool2 = AveragePooling2D(pool_size=(block._keras_shape[ROW_AXIS], block._keras_shape[COL_AXIS]), strides=(1, 1))(block)
        flatten1 = Flatten()(pool2)

        if mode == "categorical":
            dense = Dense(output_dim=num_outputs, init="he_normal", activation="softmax")(flatten1)
        elif mode == "binary":
            dense = Dense(output_dim=1, init="he_normal", activation="sigmoid")(flatten1)
        else:
            dense = None
            raise Exception("mode should either be categorical or binary")

        model = Model(input=input, output=dense)
        return model

    @staticmethod
    def build_resnet_18(input_shape, num_outputs):
        model = ResNetBuilder.build(input_shape, num_outputs, basic_block, [2, 2, 2, 2])
        plot_model_cwd(model, visual_path, "resnet_18.png")
        return model

    @staticmethod
    def build_resnet_34(input_shape, num_outputs):
        model = ResNetBuilder.build(input_shape, num_outputs, basic_block, [3, 4, 6, 3])
        plot_model_cwd(model, visual_path, "resnet_34.png")
        return model

    @staticmethod
    def build_resnet_34_binary(input_shape):
        model = ResNetBuilder.build(input_shape, 1, basic_block, [3, 4, 6, 3], mode="binary")
        plot_model_cwd(model, visual_path, "resnet_34_binary.png")
        return model

    @staticmethod
    def build_resnet_50(input_shape, num_outputs):
        model = ResNetBuilder.build(input_shape, num_outputs, bottleneck, [3, 4, 6, 3])
        plot_model_cwd(model, visual_path, "resnet_50.png")
        return model

    @staticmethod
    def build_resnet_101(input_shape, num_outputs):
        model = ResNetBuilder.build(input_shape, num_outputs, bottleneck, [3, 4, 23, 3])
        plot_model_cwd(model, visual_path, "resnet_101.png")
        return model

    @staticmethod
    def build_resnet_152(input_shape, num_outputs):
        model = ResNetBuilder.build(input_shape, num_outputs, bottleneck, [3, 8, 36, 3])
        plot_model_cwd(model, visual_path, "resnet_152.png")
        return model


def main():
    model = ResNetBuilder.build_resnet_18((3, 224, 224), 1000)
    model.compile(loss="categorical_crossentropy", optimizer="sgd")
    model.summary()


if __name__ == '__main__':
    main()
