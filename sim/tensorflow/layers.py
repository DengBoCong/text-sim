#! -*- coding: utf-8 -*-
""" Tensorflow Common Modules
"""
# Author: DengBoCong <bocongdeng@gmail.com>
#
# License: MIT License

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf
import tensorflow.keras as keras
from sim.tensorflow.common import recompute_grad
from sim.tensorflow.common import scaled_dot_product_attention
from typing import Any


class PositionEmbedding(keras.layers.Layer):
    """定义可训练的位置Embedding
    """

    def __init__(self,
                 input_dim: int,
                 output_dim: int,
                 merge_mode: str = "add",
                 hierarchical: Any = None,
                 custom_position_ids: bool = False,
                 embeddings_initializer: Any = "zeros",
                 **kwargs):
        """
        :param input_dim: 输入维度
        :param output_dim: 输出维度
        :param merge_mode: 输入和position合并的方式
        :param hierarchical: 是否层次分解位置编码
        :param custom_position_ids: 是否传入自定义位置编码id
        :param embeddings_initializer: 初始化器
        """
        super(PositionEmbedding, self).__init__(**kwargs)
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.merge_mode = merge_mode
        self.hierarchical = hierarchical
        self.custom_position_ids = custom_position_ids
        self.embeddings_initializer = embeddings_initializer

    def build(self, input_shape):
        super(PositionEmbedding, self).build(input_shape)
        self.embeddings = self.add_weight(
            name="embeddings",
            shape=(self.input_dim, self.output_dim),
            initializer=self.embeddings_initializer
        )

    def call(self, inputs, *args, **kwargs):
        """如果传入自定义position_ids，那么第二个输入为自定义的位置id
        """
        if self.custom_position_ids:
            inputs, position_ids = inputs
            if "int" not in position_ids.dtype.name:
                position_ids = tf.cast(x=position_ids, dtype=tf.int32)
        else:
            batch_size, seq_len = tf.shape(inputs)[0], tf.shape(inputs)[1]
            position_ids = tf.expand_dims(input=tf.range(start=0, limit=seq_len, delta=1), axis=0)

        if self.hierarchical:
            alpha = 0.4 if self.hierarchical is True else self.hierarchical
            embeddings = self.embeddings - alpha * self.embeddings[:1]
            embeddings = embeddings / (1 - alpha)
            embeddings_x = tf.gather(params=embeddings, indices=position_ids // self.input_dim)
            embeddings_y = tf.gather(params=embeddings, indices=position_ids % self.input_dim)
            embeddings = alpha * embeddings_x + (1 - alpha) * embeddings_y
        else:
            if self.custom_position_ids:
                embeddings = tf.gather(params=self.embeddings, indices=position_ids)
            else:
                embeddings = self.embeddings[None, :seq_len]

        if self.merge_mode == "add":
            return inputs + embeddings
        elif self.merge_mode == "mul":
            return inputs * (embeddings + 1.0)
        elif self.merge_mode == "zero":
            return embeddings
        else:
            if not self.custom_position_ids:
                embeddings = tf.tile(input=embeddings, multiples=[batch_size, 1, 1])
            return tf.concat(values=[inputs, embeddings], axis=-1)

    def get_config(self):
        config = {
            "input_dim": self.input_dim,
            "output_dim": self.output_dim,
            "merge_model": self.merge_mode,
            "hierarchical": self.hierarchical,
            "embeddings_initializer": keras.initializers.serialize(initializer=self.embeddings_initializer),
            "custom_position_ids": self.custom_position_ids
        }
        base_config = super(PositionEmbedding, self).get_config()
        base_config.update(config)
        return base_config


class Embedding(keras.layers.Embedding):
    """扩展Embedding层
    """

    def compute_mask(self, inputs, mask=None):
        """为了适配T5，保证第一个token不被mask
        """
        if keras.backend.ndim(inputs) == 2:
            mask = super(Embedding, self).compute_mask(inputs, mask)
            if mask is not None:
                mask1 = keras.backend.ones_like(mask[:, :1], dtype="bool")
                mask2 = mask[:, 1:]
                return keras.backend.concatenate([mask1, mask2], 1)
        else:
            return mask

    def call(self, inputs, mode: str = "embedding"):
        """新增mode参数，可以为embedding或dense。如果为embedding，
           则等价于普通Embedding层；如果为dense，则等价于无bias的Dense层。
        """
        if mode == "embedding":
            return super(Embedding, self).call(inputs)
        else:
            return tf.linalg.matmul(a=inputs, b=self.embeddings, transpose_b=True)

    def compute_output_shape(self, input_shape):
        """关于判据，本来是通过缓存call时的mode参数来判断的，但是后来发现
        Keras在使用compute_output_shape的时候不一定配套调用了call函数，
        所以缓存的mode可能是不准的，因此只能出此下策。
        """
        if len(input_shape) == 2:
            return super(Embedding, self).compute_output_shape(input_shape)
        else:
            return input_shape[:2] + (keras.backend.int_shape(self.embeddings)[0],)


class BiasAdd(keras.layers.Layer):
    """偏置项
    """

    def __init__(self, **kwargs):
        super(BiasAdd, self).__init__(**kwargs)

    def build(self, input_shape):
        super(BiasAdd, self).build(input_shape)
        self.bias = self.add_weight(name="bias", shape=(input_shape[-1],), initializer="zeros")

    def call(self, inputs, *args, **kwargs):
        return keras.backend.bias_add(inputs, self.bias)


class FeedForward(keras.layers.Layer):
    """FeedForward层
    """

    def __init__(self,
                 units: int,
                 activation: Any = "gelu",
                 use_bias: bool = True,
                 kernel_initializer: Any = "glorot_uniform",
                 **kwargs):
        """
        https://arxiv.org/abs/2002.05202
        :param units: 输出维度
        :param use_bias: 是否使用偏差项
        :param activation: 激活函数，如果传入的是list，则将使用门控线性单元
        :param kernel_initializer: 初始化器
        :param name: 模型名
        """
        super(FeedForward, self).__init__(**kwargs)
        self.units = units
        self.activation = [activation] if not isinstance(activation, list) else activation
        self.use_bias = use_bias
        self.kernel_initializer = kernel_initializer

    def build(self, input_shape):
        super(FeedForward, self).build(input_shape)
        for index in range(len(self.activation)):
            setattr(self, f"inner_dense_{index}", keras.layers.Dense(
                units=self.units,
                activation=self.activation[index],
                use_bias=self.use_bias,
                kernel_initializer=self.kernel_initializer
            ))

        self.output_dense = keras.layers.Dense(
            units=input_shape[-1],
            use_bias=self.use_bias,
            kernel_initializer=self.kernel_initializer
        )

    @recompute_grad
    def call(self, inputs, *args, **kwargs):
        outputs = self.inner_dense_0(inputs)
        for index in range(1, len(self.activation)):
            outputs = outputs * getattr(self, f"inner_dense_{index}")(inputs)

        outputs = self.output_dense(outputs)

        return outputs

    def get_config(self):
        config = {
            'units': self.units,
            'activation': [keras.activations.serialize(act) for act in self.activation],
            'use_bias': self.use_bias,
            'kernel_initializer': keras.initializers.serialize(self.kernel_initializer),
        }
        base_config = super(FeedForward, self).get_config()
        base_config.update(config)
        return base_config


class BertSelfAttention(keras.layers.Layer):
    """定义Self-Attention
    """

    def __init__(self,
                 num_heads: int,
                 head_size: int,
                 batch_size: int,
                 attention_dropout: float,
                 use_bias: bool = True,
                 key_size: int = None,
                 hidden_size: int = None,
                 initializer: Any = "glorot_uniform",
                 **kwargs):
        """
        :param num_heads: 注意力头数
        :param head_size: Attention中V的head_size
        :param batch_size: batch size
        :param attention_dropout: Attention矩阵的Dropout比例
        :param use_bias: 是否加上偏差项
        :param key_size: Attention中Q,K的head_size
        :param hidden_size: 编码维度
        :param initializer: 初始化器
        """
        super(BertSelfAttention, self).__init__(**kwargs)
        self.num_heads = num_heads
        self.head_size = head_size
        self.batch_size = batch_size
        self.attention_dropout = attention_dropout
        self.use_bias = use_bias
        self.key_size = key_size if key_size is not None else head_size
        self.hidden_size = hidden_size if hidden_size is not None else num_heads * head_size
        self.initializer = initializer

    def build(self, input_shape):
        super(BertSelfAttention, self).build(input_shape)
        self.query_dense = keras.layers.Dense(units=self.key_size * self.num_heads,
                                              use_bias=self.use_bias, kernel_initializer=self.initializer)
        self.key_dense = keras.layers.Dense(units=self.key_size * self.num_heads,
                                            use_bias=self.use_bias, kernel_initializer=self.initializer)
        self.value_dense = keras.layers.Dense(units=self.head_size * self.num_heads,
                                              use_bias=self.use_bias, kernel_initializer=self.initializer)
        self.output_dense = keras.layers.Dense(units=self.hidden_size, use_bias=self.use_bias,
                                               kernel_initializer=self.initializer)

    def transpose_for_scores(self, input_tensor: tf.Tensor, head_size: int):
        """分拆最后一个维度到 (num_heads, depth)
        :param input_tensor: 输入
        :param head_size: 每个注意力头维数
        """
        input_tensor = tf.reshape(tensor=input_tensor, shape=(self.batch_size, -1, self.num_heads, head_size))
        return tf.transpose(input_tensor, perm=[0, 2, 1, 3])

    @recompute_grad
    def call(self, inputs, *args, **kwargs):
        query, key, value, mask = inputs
        query = self.query_dense(query)
        key = self.key_dense(key)
        value = self.value_dense(value)

        query = self.transpose_for_scores(input_tensor=query, head_size=self.key_size)
        key = self.transpose_for_scores(input_tensor=key, head_size=self.key_size)
        value = self.transpose_for_scores(input_tensor=value, head_size=self.head_size)

        scaled_attention, attention_weights = scaled_dot_product_attention(
            query=query,
            key=key,
            value=value,
            batch_size=self.batch_size,
            hidden_size=self.hidden_size,
            attention_head_size=self.head_size,
            dropout=self.attention_dropout,
            mask=mask
        )

        attn_outputs = self.output_dense(scaled_attention)

        return attn_outputs, attention_weights

    def get_config(self):
        config = {
            "num_heads": self.num_heads,
            "head_size": self.head_size,
            "attention_dropout": self.attention_dropout,
            "use_bias": self.use_bias,
            "key_size": self.key_size,
            "hidden_size": self.hidden_size,
            "initializer": keras.initializers.serialize(initializer=self.initializer),
        }
        base_config = super(BertSelfAttention, self).get_config()
        base_config.update(config)
        return base_config


class BertOutput(keras.layers.Layer):
    """Bert 规范化输出
    """

    def __init__(self,
                 with_pool: Any = True,
                 with_nsp: Any = False,
                 with_mlm: Any = False,
                 initializer: Any = None,
                 **kwargs):
        assert with_pool or with_mlm  # 使用的话，二选其一传
        self.with_pool = with_pool
        self.with_nsp = with_nsp
        self.with_mlm = with_mlm
        self.initializer = keras.initializers.TruncatedNormal(stddev=0.02) if initializer is None else initializer

        if self.with_pool:
            assert "hidden_size" in kwargs
            self.pool_activation = 'tanh' if with_pool is True else with_pool
            self.hidden_size = kwargs["hidden_size"]

        if self.with_mlm:
            assert "embedding_size" in kwargs and "hidden_act" in kwargs \
                   and "layer_norm_eps" in kwargs and "token_embeddings" in kwargs
            self.mlm_activation = 'softmax' if with_mlm is True else with_mlm
            self.embedding_size = kwargs["embedding_size"]
            self.hidden_act = kwargs["hidden_act"]
            self.layer_norm_eps = kwargs["layer_norm_eps"]
            self.token_embeddings = kwargs["token_embeddings"]

        del kwargs["hidden_size"]
        del kwargs["embedding_size"]
        del kwargs["hidden_act"]
        del kwargs["layer_norm_eps"]
        del kwargs["token_embeddings"]
        super(BertOutput, self).__init__(**kwargs)

    def build(self, input_shape):
        super(BertOutput, self).build(input_shape)
        # self.token_embeddings = Embedding(
        #     input_dim=30522,
        #     output_dim=768,
        #     embeddings_initializer=keras.initializers.TruncatedNormal(stddev=0.02),
        #     mask_zero=True,
        #     name="embedding-token"
        # )
        if self.with_pool:
            self.pooler = keras.layers.Lambda(lambda x: x[:, 0], name=f"{self.name}-pooler")
            self.pooler_dense = keras.layers.Dense(units=self.hidden_size, activation=self.pool_activation,
                                                   kernel_initializer=self.initializer,
                                                   name=f"{self.name}-pooler-dense")
            if self.with_nsp:
                self.nsp_prob = keras.layers.Dense(units=2, activation="softmax", kernel_initializer=self.initializer,
                                                   name=f"{self.name}-nsp-prob")

        if self.with_mlm:
            self.mlm_dense = keras.layers.Dense(units=self.embedding_size, activation=self.hidden_act,
                                                kernel_initializer=self.initializer, name=f"{self.name}-mlm-dense")
            self.mlm_norm = keras.layers.LayerNormalization(epsilon=self.layer_norm_eps, name=f"{self.name}-mlm-norm")
            # sub_outputs = kwargs["token_embeddings"](sub_outputs, mode="dense")
            self.mlm_bias = BiasAdd(name=f"{self.name}-mlm-bias")
            self.mlm_act = keras.layers.Activation(activation=self.mlm_activation, name=f"{self.name}-mlm-activation")

    def call(self, inputs, *args, **kwargs):
        outputs = []
        if self.with_pool:
            sub_outputs = self.pooler(inputs)
            sub_outputs = self.pooler_dense(sub_outputs)

            if self.with_nsp:
                sub_outputs = self.nsp_prob(sub_outputs)
            outputs.append(sub_outputs)

        if self.with_mlm:
            sub_outputs = self.mlm_dense(inputs)
            sub_outputs = self.mlm_norm(sub_outputs)
            sub_outputs = self.token_embeddings(sub_outputs, mode="dense")
            sub_outputs = self.mlm_bias(sub_outputs)
            sub_outputs = self.mlm_act(sub_outputs)
            outputs.append(sub_outputs)
